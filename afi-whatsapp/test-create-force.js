const api = require('@actual-app/api');
const serverURL = "http://actual-server:5006";
const password = "dammit00";

(async () => {
  await api.init({ dataDir: './force_create', serverURL, password });
  try {
      console.log("Sending create-budget...");
      await api.internal.send('create-budget', { testMode: false, showSchedules: true });
      // The result might be nothing or the ID?
      // create-budget usually loads it too.
      console.log("Command sent.");
      
      // Now list budgets
      const budgets = await api.getBudgets();
      console.log("Budgets:", budgets);
      
  } catch(e) {
      console.error("Failed:", e);
  }
  await api.shutdown();
})();
