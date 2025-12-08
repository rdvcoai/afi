const { Client, LocalAuth } = require('whatsapp-web.js');
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const bridge = require('./actual-bridge'); // Importar el puente
const express = require('express');
const fs = require('fs');
const path = require('path');
const app = express();
app.use(express.json());
let isReady = false;

const MEDIA_DIR = process.env.MEDIA_DIR || '/usr/src/app/media';
if (!fs.existsSync(MEDIA_DIR)) {
    fs.mkdirSync(MEDIA_DIR, { recursive: true });
}

// 1. Activar Modo Sigilo (Anti-Ban Capa 1)
puppeteer.use(StealthPlugin());

// Configuración del navegador Anti-Huella
const puppeteerConfig = {
    headless: true,
    args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-accelerated-2d-canvas',
        '--no-first-run',
        '--no-zygote',
        // '--proxy-server=http://user:pass@host:port' // Activar esto en PROD
    ]
};

// 2. Inicializar Cliente con Persistencia
const client = new Client({
    authStrategy: new LocalAuth({ dataPath: './session' }),
    puppeteer: puppeteerConfig,
    // Usamos User-Agent de Windows real para consistencia
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'
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
        let mediaPath = null;
        let mediaMime = null;
        if (msg.hasMedia) {
            try {
                const media = await msg.downloadMedia();
                if (media && media.data) {
                    const buffer = Buffer.from(media.data, 'base64');
                    const ext = media.mimetype ? `.${media.mimetype.split('/')[1]}` : '';
                    const fname = `wa_${Date.now()}${ext}`;
                    mediaPath = path.join(MEDIA_DIR, fname);
                    fs.writeFileSync(mediaPath, buffer);
                    mediaMime = media.mimetype || 'application/octet-stream';
                    console.log(`💾 Media guardada en ${mediaPath}`);
                }
            } catch (e) {
                console.error("❌ No se pudo guardar media:", e);
            }
        }

        // CORRECCIÓN: Asegurar nombres de campos explícitos y tipos correctos
        const payload = {
            // "from" es palabra reservada en algunos contextos, enviamos como string
            "from_user": msg.from,
            "body": msg.body || "", // Evitar null
            "hasMedia": msg.hasMedia || false,
            "timestamp": msg.timestamp || Math.floor(Date.now() / 1000),
            "media_path": mediaPath,
            "media_mime": mediaMime,
        };

        console.log('📤 Enviando payload a Brain:', JSON.stringify(payload));

        // Enviar al Cerebro (Python)
        const response = await axios.post('http://afi-core:8080/webhook/whatsapp', payload);

        // Si el cerebro responde, contestar al usuario
        if (response.data && response.data.reply) {
            const reply = response.data.reply;
            const chat = await msg.getChat();

            // Simular comportamiento humano (Escribiendo...)
            await chat.sendStateTyping();

            // Retardo aleatorio para evitar detección de máquina (2-4 seg)
            const delay = Math.floor(Math.random() * 2000) + 2000;
            await new Promise(r => setTimeout(r, delay));

            // DETECTOR DE COMANDOS INTERNOS
            // Si la respuesta empieza con "CMD:TRANSACTION", es una orden para el puente
            if (reply.startsWith("CMD:TRANSACTION")) {
                try {
                    const jsonStr = reply.replace("CMD:TRANSACTION", "").trim();
                    const data = JSON.parse(jsonStr);
                    // data = { budget_id, date, amount, payee, notes }

                    console.log('💰 Comando de transacción detectado:', data);

                    const { budget_id, ...tx } = data;
                    await bridge.addTransaction(tx, budget_id);

                    await client.sendMessage(msg.from, `✅ Registrado: ${data.amount} COP en ${data.payee}\n\n${data.notes}`);
                } catch (e) {
                    console.error("❌ Error en puente Actual:", e);
                    await client.sendMessage(msg.from, "❌ Error guardando en la bóveda. Verificar logs.");
                }
            } else {
                // Respuesta normal de texto
                await client.sendMessage(msg.from, reply);
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
        const chatId = phone.includes('@') ? phone : `${phone}@c.us`;
        await client.sendMessage(chatId, message);
        console.log(`📤 Push enviado a ${chatId}`);
        res.send({ status: 'sent' });
    } catch (e) {
        console.error("Error enviando push:", e);
        res.status(500).send(e.message);
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
