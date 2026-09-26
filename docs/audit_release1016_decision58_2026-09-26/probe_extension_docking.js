// Negative-path audit of the actual new docking handler; no browser automation.
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const root = path.resolve(__dirname, '../..');
const text = fs.readFileSync(path.join(root, 'extension/app.js'), 'utf8');
const begin = text.indexOf('// Open app in new tab / toggle sidepanel');
const end = text.indexOf('// Expand Preview Table into Full Tab', begin);
async function probe(hasApi) {
  let click;
  let closed = false;
  let attempted = false;
  const context = {
    isFullTab: true,
    btnOpenTab: {addEventListener: (name, handler) => {click = handler;}},
    currentCsvText: 'synthetic', currentCsvFilename: 'synthetic.csv',
    currentAccountsFound: [], currentDuplicatesCount: 0,
    chrome: {
      storage: {local: {set: (data, callback) => callback()}},
      windows: {getCurrent: async () => ({id: 1})},
      sidePanel: hasApi ? {open: async () => {attempted = true; throw new Error('synthetic opening failure');}} : {}
    },
    window: {close: () => {closed = true;}},
    console: {warn: () => {}}
  };
  vm.runInNewContext(text.slice(begin, end), context);
  await click();
  await new Promise(resolve => setImmediate(resolve));
  return {sidepanel_api_present: hasApi, open_attempted: attempted, tab_closed_without_open_success: closed};
}
(async () => {
  const result = {scope: 'actual handler in VM; failure injection, not real Chrome E2E',
                  failures: [await probe(true), await probe(false)]};
  fs.writeFileSync(path.join(__dirname, 'extension_docking_results.json'), JSON.stringify(result, null, 2));
  process.stdout.write(JSON.stringify(result, null, 2));
})();
