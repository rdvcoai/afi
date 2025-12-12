const api = require('@actual-app/api');
const serverURL = "http://actual-server:5006";
const password = process.env.ACTUAL_PASSWORD || "dammit00";

(async () => {
  try {
    console.log(`Connecting to ${serverURL}...`);
    await api.init({ dataDir: './new_budget_data', serverURL, password });
    console.log("✅ Auth success. Creating new budget...");
    
    // Create budget
    const id = await api.createBudget({ testMode: false, showSchedules: true });
    console.log(`✅ BUDGET CREATED. ID: ${id}`);
    
    await api.shutdown();
  } catch (e) {
    console.error("❌ Failed:", e);
  }
})();
