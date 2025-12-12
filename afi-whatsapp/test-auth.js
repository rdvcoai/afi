const api = require('@actual-app/api');
const serverURL = "http://actual-server:5006";
const password = "dammit00"; // New password
const budgetId = "6841dc8c-0245-40a1-ac52-2859fcd6835c";

(async () => {
  try {
    console.log(`Connecting to ${serverURL} with password ${password}`);
    await api.init({ dataDir: './test_auth_data_2', serverURL, password });
    console.log("✅ Auth success");
    
    console.log(`Downloading budget: ${budgetId}`);
    await api.downloadBudget(budgetId);
    console.log("✅ Download success");
    
    await api.shutdown();
  } catch (e) {
    console.error("❌ Failed:", e);
  }
})();
