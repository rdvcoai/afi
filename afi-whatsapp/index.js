const { Client, LocalAuth } = require('whatsapp-web.js');
// const puppeteer = require('puppeteer-extra');
// const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const bridge = require('./actual-bridge'); // Importar el puente
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
        // Hard override: priorizar ADMIN_PHONE; si no existe, usar el número normalizado
        const adminNumber = process.env.ADMIN_PHONE ? process.env.ADMIN_PHONE.replace(/\D/g, '') : null;
        const resolvedNumber = adminNumber || normalizedFrom;

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

            // Chat ID canónico: siempre ADMIN_PHONE (evita LID)
            const targetPhone = adminNumber || resolvedNumber || normalizedFrom || '573002127123';
            const chatId = `${targetPhone}@c.us`;
            console.log(`💉 Inyectando respuesta directa a: ${chatId}`);

            try {
                // Inyección directa en la página para evitar validaciones LID de la librería
                await client.pupPage.evaluate(async (to, body) => {
                    const chat = await window.Store.Chat.get(to);
                    if (!chat) {
                        console.error("Chat no encontrado en Store:", to);
                        return;
                    }
                    await chat.sendMessage(body);
                }, chatId, reply);
                console.log(`📤 Respuesta inyectada correctamente.`);
            } catch (e) {
                console.error("❌ Falló la inyección directa:", e.message);
            }
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
        const chatId = `${cleanTo}@c.us`;
        // Intentar precargar chat
        try {
            const chat = await client.getChatById(chatId);
            await chat.sendStateTyping();
        } catch (e) {
            console.log("⚠️ No pude prefetchear chat en /send-message, intento inyección directa...");
        }
        // Inyección directa
        await client.pupPage.evaluate(async (dest, text) => {
            let chat = await window.Store.Chat.get(dest);
            if (!chat) {
                const contact = await window.Store.Contact.get(dest);
                if (contact) {
                    chat = await window.Store.Chat.find(contact);
                }
            }
            if (!chat) {
                throw new Error(`Chat ${dest} no encontrado en Store web.`);
            }
            await chat.sendMessage(text);
        }, chatId, message);
        console.log(`📤 Push enviado a ${chatId}`);
        res.send({ status: 'sent' });
    } catch (e) {
        console.error("Error enviando push:", e);
        res.status(500).send(e.message);
    }
});

// Endpoint push alternativo (acepta 'to' como número plano o chatId)
app.post('/send', async (req, res) => {
    try {
        const { to, message } = req.body || {};
        if (!to || !message) return res.status(400).send('Faltan datos');
        if (!isReady) return res.status(503).send('WhatsApp client not ready');

        const cleanTo = to.replace('+', '').replace('@c.us', '');
        const chatId = `${cleanTo}@c.us`;
        console.log(`📨 Intentando Push a: ${chatId}`);

        // Paso 1: intentar precargar el chat (evita "Chat no encontrado")
        try {
            const chat = await client.getChatById(chatId);
            await chat.sendStateTyping();
        } catch (e) {
            console.log("⚠️ No pude hacer pre-fetch del chat, intentaré inyección directa...");
        }

        // Paso 2: Inyección directa con fallback de búsqueda en Store
        await client.pupPage.evaluate(async (dest, text) => {
            let chat = await window.Store.Chat.get(dest);
            if (!chat) {
                const contact = await window.Store.Contact.get(dest);
                if (contact) {
                    chat = await window.Store.Chat.find(contact);
                }
            }
            if (!chat) {
                throw new Error(`Chat ${dest} no encontrado en Store web.`);
            }
            await chat.sendMessage(text);
        }, chatId, message);

        console.log(`✅ Push exitoso a ${chatId}`);
        res.json({ success: true });
    } catch (e) {
        console.error("❌ Error en Push /send:", e);
        res.status(500).json({ error: e.message });
    }
});

// Endpoint: últimas transacciones
app.get('/transactions', async (_req, res) => {
    try {
        const data = await bridge.getLastTransactions(5);
        res.json(data);
    } catch (e) {
        res.status(500).send(e.message);
    }
});

// Endpoint: búsqueda de transacciones (conciliación)
app.post('/transactions/search', async (req, res) => {
    try {
        const data = await bridge.searchTransactions(req.body || {});
        res.json(data);
    } catch (e) {
        res.status(500).send(e.message);
    }
});

// Endpoint: crear transacción directa (para auditoría histórica)
app.post('/transaction/add', async (req, res) => {
    try {
        const { budget_id, ...tx } = req.body || {};
        const { date, amount, payee } = tx;
        if (!date || typeof amount !== 'number' || !payee) return res.status(400).send('Faltan datos');
        await bridge.addTransaction(tx, budget_id);
        res.json({ status: 'ok' });
    } catch (e) {
        res.status(500).send(e.message);
    }
});

// Endpoint: actualizar transacción
app.post('/transaction/update', async (req, res) => {
    try {
        const { id, updates } = req.body || {};
        if (!id || !updates) return res.status(400).send('Faltan datos');
        await bridge.updateTransaction(id, updates);
        res.json({ status: 'ok' });
    } catch (e) {
        res.status(500).send(e.message);
    }
});

// Endpoint: crear cuenta directa
app.post('/accounts', async (req, res) => {
    try {
        const { name, type, balance } = req.body || {};
        if (!name) return res.status(400).send('Falta nombre');
        const id = await bridge.createAccount(name, type || "checking", balance || 0);
        res.json({ success: true, id });
    } catch (e) {
        console.error("❌ Error creando cuenta:", e);
        res.status(500).json({ error: e.message });
    }
});

// Endpoint: sincronizar cuentas detectadas
app.post('/accounts/sync', async (req, res) => {
    try {
        const { accounts } = req.body || {};
        const created = await bridge.syncAccounts(accounts || []);
        res.json({ created });
    } catch (e) {
        res.status(500).send(e.message);
    }
});

// Endpoint: importación masiva de transacciones
app.post('/transactions/import', async (req, res) => {
    try {
        const { accountId, transactions } = req.body || {};
        if (!accountId || !transactions) return res.status(400).send('Faltan datos (accountId, transactions)');
        const result = await bridge.importTransactions(accountId, transactions);
        res.json({ success: true, result });
    } catch (e) {
        console.error("❌ Error importando transacciones:", e);
        res.status(500).json({ error: e.message });
    }
});

// Endpoint: crear categoría (stub)
app.post('/category/create', async (req, res) => {
    try {
        const { name, group_name } = req.body || {};
        if (!name) return res.status(400).send('Falta nombre');
        const id = await bridge.createCategory(name, group_name || "Gastos Variables");
        res.json({ id, status: 'created' });
    } catch (e) {
        console.error(e);
        res.status(500).json({ error: e.message });
    }
});

// Endpoint: bulk categorize (stub)
app.post('/category/bulk-categorize', async (req, res) => {
    try {
        const { category_name, keywords_list } = req.body || {};
        if (!category_name) return res.status(400).send('Falta categoría');
        const count = await bridge.bulkCategorize(category_name, keywords_list || []);
        res.json({ updated: count, status: 'success' });
    } catch (e) {
        console.error(e);
        res.status(500).json({ error: e.message });
    }
});

app.listen(3000, () => {
    console.log('🌐 API Push escuchando en puerto 3000');
});

client.initialize();
