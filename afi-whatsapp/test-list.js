const api = require('@actual-app/api');
const serverURL = "http://actual-server:5006";
const password = "dammit00";

(async () => {
  try {
    await api.init({ dataDir: './list_data', serverURL, password });
    const budgets = await api.getBudgets();
    console.log("Budgets:", budgets);
    await api.shutdown();
  } catch (e) {
    console.error("Failed:", e);
  }
})();
