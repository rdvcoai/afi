const api = require('@actual-app/api');
const fs = require('fs');

// Configuración
const DEFAULT_BUDGET_ID =
    process.env.ACTUAL_BUDGET_ID_MAIN ||
    process.env.ACTUAL_BUDGET_ID || // retrocompatibilidad
    null;
const SERVER_URL = process.env.ACTUAL_SERVER_URL || "http://actual-server:5006";
const PASSWORD = process.env.ACTUAL_PASSWORD;
const ACCOUNT_ID = process.env.ACTUAL_ACCOUNT_ID; // opcional, si no se setea tomamos la primera cuenta

let isConnected = false;
let defaultAccountId = null;
let currentBudgetId = null;

async function connect() {
    if (isConnected) return;
    // Carpeta temporal para cache de Actual
    if (!fs.existsSync('./temp_budget')) fs.mkdirSync('./temp_budget');

    if (!DEFAULT_BUDGET_ID) {
        throw new Error("ACTUAL_BUDGET_ID_MAIN/ACTUAL_BUDGET_ID no está definido en .env");
    }

    await api.init({
        dataDir: './temp_budget',
        serverURL: SERVER_URL,
        password: PASSWORD,
    });

    // Descargar presupuesto inicial (existente en el servidor)
    await api.downloadBudget(DEFAULT_BUDGET_ID);
    currentBudgetId = DEFAULT_BUDGET_ID;

    // Seleccionar cuenta destino
    const accounts = await api.getAccounts();
    if (ACCOUNT_ID) {
        defaultAccountId = ACCOUNT_ID;
    } else if (accounts.length > 0) {
        defaultAccountId = accounts[0].id;
        console.log(`ℹ️ Usando primera cuenta como destino: ${accounts[0].name} (${accounts[0].id})`);
    } else {
        throw new Error("No hay cuentas en Actual. Crea una cuenta y reinicia el servicio.");
    }
    isConnected = true;
    console.log("💰 Puente Actual Budget: Conectado");
}

async function ensureBudget(targetBudgetId) {
    const budgetId = targetBudgetId || DEFAULT_BUDGET_ID;
    if (!budgetId) {
        throw new Error("No se recibió budget_id ni hay DEFAULT_BUDGET_ID configurado.");
    }
    if (currentBudgetId !== budgetId) {
        console.log(`🔄 Cambiando a presupuesto: ${budgetId}`);
        await api.downloadBudget(budgetId);
        currentBudgetId = budgetId;
        const accounts = await api.getAccounts();
        if (ACCOUNT_ID && accounts.find(a => a.id === ACCOUNT_ID)) {
            defaultAccountId = ACCOUNT_ID;
        } else if (accounts.length > 0) {
            defaultAccountId = accounts[0].id;
            console.log(`ℹ️ Cuenta destino ahora: ${accounts[0].name} (${accounts[0].id})`);
        } else {
            throw new Error("No hay cuentas en Actual para este presupuesto.");
        }
    }
    return budgetId;
}

async function addTransaction(data, targetBudgetId) {
    if (!isConnected) await connect();

    await ensureBudget(targetBudgetId);

    try {
        const { date, amount, payee, category, notes } = data;
        const amountInCents = api.utils.amountToInteger(amount);

        await api.importTransactions(defaultAccountId, [{
            date: date, // 'YYYY-MM-DD'
            amount: amountInCents,
            payee_name: payee,
            notes: notes,
            // category: category // Mapear categorías es complejo, por ahora dejemos sin categoría
        }]);

        console.log(`💸 Gasto registrado: ${amount} en ${payee}`);
        return "OK";
    } catch (e) {
        console.error("❌ Error registrando transacción:", e);
        return "ERROR";
    }
}

// Leer últimas N transacciones (por fecha)
async function getLastTransactions(count = 5) {
    if (!isConnected) await connect();
    const start = new Date('2024-01-01');
    const end = new Date();
    const txs = await api.getTransactions(defaultAccountId, start, end);
    return txs
        .sort((a, b) => b.date.localeCompare(a.date))
        .slice(0, count);
}

// Actualizar una transacción existente
async function updateTransaction(id, updates) {
    if (!isConnected) await connect();
    // Normalizar campos permitidos por Actual
    const allowed = ['amount', 'notes', 'category', 'payee', 'imported_payee', 'date', 'cleared', 'reconciled'];
    const clean = {};
    for (const [k, v] of Object.entries(updates)) {
        if (k === 'payee') {
            clean.imported_payee = v;
        } else if (allowed.includes(k)) {
            clean[k] = v;
        }
    }
    if (Object.keys(clean).length === 0) {
        throw new Error("No hay campos válidos para actualizar.");
    }
    await api.updateTransaction(id, clean);
    return "UPDATED";
}

// Buscar transacciones por rango de fecha y monto (para conciliación)
async function searchTransactions(filters = {}) {
    if (!isConnected) await connect();
    const {
        min_date,
        max_date,
        min_amount,
        max_amount,
    } = filters;

    const start = min_date ? new Date(min_date) : new Date('2023-01-01');
    const end = max_date ? new Date(max_date) : new Date();
    const minAmount = typeof min_amount === 'number' ? api.utils.amountToInteger(min_amount) : Number.NEGATIVE_INFINITY;
    const maxAmount = typeof max_amount === 'number' ? api.utils.amountToInteger(max_amount) : Number.POSITIVE_INFINITY;

    const txs = await api.getTransactions(defaultAccountId, start, end);
    return txs.filter(tx => tx.amount >= minAmount && tx.amount <= maxAmount);
}

async function getGroupId(groupName = null) {
    try {
        const categories = await api.getCategories();
        if (groupName) {
            const existingGroup = categories.find(
                (c) => c.is_group && c.name && c.name.toLowerCase() === String(groupName).toLowerCase()
            );
            if (existingGroup) return existingGroup.id;
        }
        const anyGroup = categories.find((c) => c.is_group);
        if (anyGroup) return anyGroup.id;
        const firstCat = categories.find((c) => c.group_id);
        if (firstCat && firstCat.group_id) return firstCat.group_id;

        // Si no hay grupos, intentar crear uno genérico
        const fallbackName = groupName || "General";
        const newGroup = await api.createCategoryGroup({ name: fallbackName });
        return newGroup;
    } catch (e) {
        console.error("⚠️ No se pudo crear grupo (sin grupos previos):", e?.message || e);
        return null;
    }
}

async function createCategory(name, groupName = "Gastos Variables") {
    if (!isConnected) await connect();
    const currentCats = await api.getCategories();
    const existing = currentCats.find(
        (c) => !c.is_group && c.name && c.name.toLowerCase() === String(name).toLowerCase()
    );
    if (existing) {
        console.log(`⚠️ Categoría '${name}' ya existe.`);
        return existing.id;
    }

    let groupId = await getGroupId(groupName);
    if (!groupId) {
        console.error("⚠️ No se pudo obtener groupId, usando null");
    }
    try {
        const id = await api.createCategory({ name: name, group_id: groupId });
        console.log(`✅ Categoría creada: ${name} (${id})`);
        return id;
    } catch (e) {
        console.error("❌ Error creando categoría:", e?.message || e);
        // Reintentar si fue condición de carrera y ahora existe
        const refreshed = await api.getCategories();
        const exists = refreshed.find(
            (c) => !c.is_group && c.name && c.name.toLowerCase() === String(name).toLowerCase()
        );
        if (exists) {
            console.log(`⚠️ Categoría '${name}' ya existía tras reintento.`);
            return exists.id;
        }
        throw e;
    }
}

async function bulkCategorize(categoryName, keywords = []) {
    if (!isConnected) await connect();
    console.log(`🔄 Iniciando bulk update para: ${categoryName} con keywords: ${keywords}`);

    const cats = await api.getCategories();
    const targetCat = cats.find(
        (c) => !c.is_group && c.name && c.name.toLowerCase() === String(categoryName).toLowerCase()
    );
    if (!targetCat) throw new Error(`Categoría ${categoryName} no encontrada.`);

    const sinceDate = new Date();
    sinceDate.setFullYear(sinceDate.getFullYear() - 1);
    const transactions = await api.getTransactions(null, sinceDate, new Date());

    let updatedCount = 0;
    for (const tx of transactions) {
        const description = (tx.payee_name || tx.notes || "").toLowerCase();
        const matches = keywords.some((k) => description.includes(String(k).toLowerCase()));
        if (matches) {
            await api.updateTransaction(tx.id, { category: targetCat.id });
            updatedCount++;
        }
    }

    console.log(`✅ ${updatedCount} transacciones movidas a ${categoryName}`);
    return updatedCount;
}

async function syncAccounts(accountNames = []) {
    if (!isConnected) await connect();
    const existing = await api.getAccounts();
    const created = [];
    for (const name of accountNames) {
        if (!name) continue;
        const exists = existing.find(a => a.name && a.name.toLowerCase() === String(name).toLowerCase());
        if (!exists) {
            console.log(`🏦 Creando cuenta nueva: ${name}`);
            try {
                await api.createAccount({ name: name, type: "checking" });
                created.push(name);
            } catch (e) {
                console.error("⚠️ No se pudo crear cuenta:", e);
            }
        }
    }
    return created;
}

module.exports = { addTransaction, getLastTransactions, updateTransaction, searchTransactions, syncAccounts, createCategory, bulkCategorize };
