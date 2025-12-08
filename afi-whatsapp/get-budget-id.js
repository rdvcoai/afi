const api = require('@actual-app/api');
const fs = require('fs');

const SERVER_URL = process.env.ACTUAL_SERVER_URL || "http://actual-server:5006";
const PASSWORD = process.env.ACTUAL_PASSWORD;

async function getBudgetId() {
    console.log('🔍 Conectando a Actual Budget...');

    try {
        // Crear carpeta temporal
        if (!fs.existsSync('./temp_get_id')) fs.mkdirSync('./temp_get_id');

        await api.init({
            dataDir: './temp_get_id',
            serverURL: SERVER_URL,
            password: PASSWORD,
        });

        console.log('✓ Conectado a servidor');

        // Listar presupuestos disponibles
        const budgets = await api.getBudgets();

        if (budgets.length === 0) {
            console.log('⚠️ No se encontraron presupuestos.');
            console.log('   Crea uno en https://afi.rdv.net.co primero.');
        } else {
            console.log('\n📊 Presupuestos disponibles:\n');
            budgets.forEach((budget, index) => {
                console.log(`${index + 1}. Nombre: ${budget.name}`);
                console.log(`   Sync ID: ${budget.id}`);
                console.log(`   Nube: ${budget.cloudFileId ? 'Sí' : 'No'}`);
                console.log('');
            });

            console.log('💡 Copia el Sync ID del presupuesto que quieras usar');
            console.log('   y agrégalo a tu .env como ACTUAL_BUDGET_ID=<id>');
        }

        await api.shutdown();

        // Limpiar carpeta temporal
        fs.rmSync('./temp_get_id', { recursive: true, force: true });

    } catch (e) {
        console.error('❌ Error:', e.message);
    }
}

getBudgetId();
