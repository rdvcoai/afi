const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
// const puppeteer = require('puppeteer-extra');
// const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const express = require('express');
const fs = require('fs');
const path = require('path');
const mime = require('mime-types');

const CORE_URL = process.env.CORE_URL || 'http://host.docker.internal:8080';

// Forzar ruta de Chromium si está instalada en el sistema
process.env.PUPPETEER_EXECUTABLE_PATH = process.env.PUPPETEER_EXECUTABLE_PATH || '/usr/bin/chromium';
const app = express();
app.use(express.json());
let isReady = false;
// Mapea el número normalizado al último chatId (lid/c.us) para responder en el mismo hilo
const chatMap = new Map();

// Helper: enviar mensaje con fallback (API nativa y, si falla, inyección)
async function sendToChat(chatId, body, media = null) {
    try {
        if (media) {
            await client.sendMessage(chatId, media, { caption: body });
        } else {
            await client.sendMessage(chatId, body);
        }
        console.log(`📤 Respuesta enviada con sendMessage a ${chatId}`);
        return;
    } catch (e) {
        console.log(`⚠️ sendMessage falló para ${chatId}, intento inyección directa...`, e.message);
    }
    // Fallback: Inyección directa (solo texto por ahora, media es complejo via inyección)
    if (!media) {
        try {
            await client.pupPage.evaluate(async (to, text) => {
                let chat = await window.Store.Chat.get(to);
                if (!chat) {
                    const contact = await window.Store.Contact.get(to);
                    if (contact) {
                        chat = await window.Store.Chat.find(contact);
                    }
                }
                if (!chat || !chat.sendMessage) {
                    throw new Error(`Chat ${to} no encontrado o sin sendMessage.`);
                }
                await chat.sendMessage(text);
            }, chatId, body);
            console.log(`📤 Respuesta inyectada correctamente a ${chatId}.`);
        } catch (e) {
            console.error("❌ Falló la inyección directa:", e.message);
        }
    } else {
        console.error("❌ Falló envío de media y no hay fallback de inyección para archivos.");
    }
}

const MEDIA_DIR = process.env.MEDIA_DIR || '/app/data/media';
if (!fs.existsSync(MEDIA_DIR)) {
    fs.mkdirSync(MEDIA_DIR, { recursive: true });
}

// 1. Cliente WhatsApp sin stealth (estabilidad primero)
const client = new Client({
    authStrategy: new LocalAuth({ dataPath: '/app/data/session' }),
    puppeteer: {
        executablePath: '/usr/bin/chromium',
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--no-first-run',
            '--no-zygote',
        ],
    },
    // Sin userAgent custom para minimizar fricción
});

// Eventos de Conexión
client.on('qr', (qr) => {
    console.log('⚡ ESCANEA ESTE QR PARA VINCULAR AFI:');
    qrcode.generate(qr, { small: true });
});

client.on('ready', () => {
    console.log('✅ AFI WhatsApp Interface: CONECTADO y LISTO');
    isReady = true;
});

// 3. Recepción y Reenvío de Mensajes
client.on('message', async msg => {
    // Ignorar estados y grupos por seguridad inicial
    if (msg.from.includes('status') || msg.from.includes('g.us')) return;

    console.log(`📩 Mensaje de ${msg.from}: ${msg.body.substring(0, 50)}...`);

    try {
        let mediaPayload = null;
        if (msg.hasMedia) {
            try {
                console.log(`📥 Descargando media de: ${msg.from}`);
                const media = await msg.downloadMedia();
                if (media && media.data) {
                    const extension = mime.extension(media.mimetype) || 'bin';
                    const filename = `${msg.timestamp}-${msg.id.id}.${extension}`;
                    const filePath = path.join(MEDIA_DIR, filename);
                    fs.writeFileSync(filePath, media.data, 'base64');
                    console.log(`✅ Media guardada en: ${filePath}`);
                    mediaPayload = {
                        path: filePath,
                        mime: media.mimetype || 'application/octet-stream',
                        filename,
                    };
                }
            } catch (e) {
                console.error("❌ No se pudo guardar media:", e);
            }
        }

        const normalizedFrom = msg.from ? msg.from.replace(/\D/g, '') : msg.from;
        if (normalizedFrom && msg.from) {
            chatMap.set(normalizedFrom, msg.from);
        }
        // Usar siempre el número real del mensaje; ADMIN queda como respaldo
        const adminNumber = process.env.ADMIN_PHONE ? process.env.ADMIN_PHONE.replace(/\D/g, '') : null;
        const resolvedNumber = normalizedFrom || adminNumber;

        const payload = {
            from_user: resolvedNumber,
            body: msg.body || "",
            hasMedia: msg.hasMedia || false,
            timestamp: msg.timestamp || Math.floor(Date.now() / 1000),
            media: mediaPayload,
        };

        console.log('📤 Enviando payload a Brain:', JSON.stringify(payload));

        const response = await axios.post(`${CORE_URL}/webhook/whatsapp`, payload);

        // Si el cerebro responde, contestar al usuario (inyección directa)
        if (response.data && response.data.reply) {
            const reply = response.data.reply;

            // Chat ID: priorizar el hilo exacto (lid/c.us) si lo tenemos
            const targetPhone = resolvedNumber || adminNumber || '573002127123';
            const chatId =
                chatMap.get(targetPhone) ||
                chatMap.get(resolvedNumber) ||
                (msg.from && msg.from.includes('@') ? msg.from : `${targetPhone}@c.us`);
            console.log(`💬 Respondiendo a: ${chatId}`);
            await sendToChat(chatId, reply);
        }

    } catch (error) {
        console.error('❌ Error comunicando con el Cerebro:', error.message);
    }
});

// API interna para envíos proactivos desde Python
app.post('/send-message', async (req, res) => {
    const { phone, message } = req.body || {};
    if (!phone || !message) return res.status(400).send('Faltan datos');
    if (!isReady) return res.status(503).send('WhatsApp client not ready');
    try {
        const cleanTo = phone.replace('+', '').replace('@c.us', '');
        const mappedChat = chatMap.get(cleanTo);
        const chatId = mappedChat || `${cleanTo}@c.us`;
        // Intentar precargar chat
        try {
            const chat = await client.getChatById(chatId);
            await chat.sendStateTyping();
        } catch (e) {
            console.log("⚠️ No pude prefetchear chat en /send-message, sigo con envío...");
        }
        await sendToChat(chatId, message);
        console.log(`📤 Push enviado a ${chatId}`);
        res.send({ status: 'sent' });
    } catch (e) {
        console.error("Error enviando push:", e);
        res.status(500).send(e.message);
    }
});

app.post('/send-media', async (req, res) => {
    const { phone, filePath, caption } = req.body || {};
    if (!phone || !filePath) return res.status(400).send('Faltan datos (phone, filePath)');
    if (!isReady) return res.status(503).send('WhatsApp client not ready');
    
    try {
        if (!fs.existsSync(filePath)) {
             return res.status(404).send('File not found at path');
        }
        
        const media = MessageMedia.fromFilePath(filePath);
        
        const cleanTo = phone.replace('+', '').replace('@c.us', '');
        const mappedChat = chatMap.get(cleanTo);
        const chatId = mappedChat || `${cleanTo}@c.us`;

        console.log(`🖼️ Intentando enviar MEDIA a: ${chatId}`);
        
        await sendToChat(chatId, caption || "", media);
        
        console.log(`✅ Media enviado a ${chatId}`);
        res.json({ success: true });
    } catch (e) {
        console.error("❌ Error en /send-media:", e);
        res.status(500).json({ error: e.message });
    }
});

// Endpoint push alternativo (acepta 'to' como número plano o chatId)
app.post('/send', async (req, res) => {
    try {
        const { to, message } = req.body || {};
        if (!to || !message) return res.status(400).send('Faltan datos');
        if (!isReady) return res.status(503).send('WhatsApp client not ready');

        const cleanTo = to.replace('+', '').replace('@c.us', '');
        const mappedChat = chatMap.get(cleanTo);
        const chatId = mappedChat || `${cleanTo}@c.us`;
        console.log(`📨 Intentando Push a: ${chatId}`);

        // Paso 1: intentar precargar el chat (evita "Chat no encontrado")
        try {
            const chat = await client.getChatById(chatId);
            await chat.sendStateTyping();
        } catch (e) {
            console.log("⚠️ No pude hacer pre-fetch del chat, intentaré inyección directa...");
        }

        // Paso 2: Envío con fallback
        await sendToChat(chatId, message);
        console.log(`✅ Push exitoso a ${chatId}`);
        res.json({ success: true });
    } catch (e) {
        console.error("❌ Error en Push /send:", e);
        res.status(500).json({ error: e.message });
    }
});

app.listen(3000, () => {
    console.log('🌐 API Push escuchando en puerto 3000');
});

client.initialize();
