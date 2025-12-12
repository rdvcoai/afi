const api = require('@actual-app/api');
const serverURL = "http://actual-server:5006";
const password = "dammit00";
const uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"; // New UUID

(async () => {
  try {
    await api.init({ dataDir: './load_data', serverURL, password });
    
    // Try to "load" a non-existent budget?
    // In newer API, maybe I can just initialize it?
    // No documented way to create via API without import file?
    
    // Attempt: internal method?
    // api.internal.send('create-budget', { id: uuid })?
    
    console.log("Keys:", Object.keys(api));
    
    await api.shutdown();
  } catch (e) {
    console.error("Failed:", e);
  }
})();
