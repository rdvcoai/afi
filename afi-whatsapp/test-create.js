const api = require('@actual-app/api');
const serverURL = "http://actual-server:5006";
const password = "dammit00";
const uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"; // New UUID

(async () => {
  try {
    await api.init({ dataDir: './create_data', serverURL, password });
    
    // Try download first
    try {
        await api.downloadBudget(uuid);
        console.log("Downloaded (unexpected)");
    } catch(e) {
        console.log("Download failed (expected). Trying loadBudget...");
    }

    // Try loadBudget?
    // In some versions, loading a local initialized budget and syncing pushes it?
    // But we don't have a local budget.
    
    // Attempting to use internal function or similar?
    // Actually, createBudget IS exposed in the app, but maybe not in API index?
    // Let's check api.internal
    
    // What if we import an empty buffer?
    // await api.runImport('My Budget', Buffer.from(''));
    
    await api.shutdown();
  } catch (e) {
    console.error("Failed:", e);
  }
})();
