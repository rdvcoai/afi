const api = require('@actual-app/api');
const serverURL = "http://actual-server:5006";
const password = "dammit00"; 
const budgetId = "777f11f8-ad22-46a2-b4f9-f2105c3a9668"; // The other large file found

(async () => {
  try {
    console.log(`Connecting to ${serverURL} with password ${password}`);
    await api.init({ dataDir: './test_auth_data_3', serverURL, password });
    console.log("✅ Auth success");
    
    console.log(`Downloading budget: ${budgetId}`);
    await api.downloadBudget(budgetId);
    console.log("✅ Download success");
    
    await api.shutdown();
  } catch (e) {
    console.error("❌ Failed:", e);
  }
})();
