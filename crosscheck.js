// Extract the engine from regime.html, stub the DOM, and compare its output
// with the Python engine on byte-identical input.
const fs = require('fs');

const html = fs.readFileSync('regime.html', 'utf8');
const js = html.split('<script>')[1].split('<\/script>')[0];

// Minimal DOM stub so the wiring section at the bottom doesn't explode.
const el = () => ({ textContent:'', innerHTML:'', title:'', className:'',
  style:{}, disabled:false, value:'20',
  classList:{add(){},remove(){},toggle(){}},
  addEventListener(){}, appendChild(){}, setAttribute(){}, click(){} });
global.document = { getElementById: el, createElement: el };
global.fetch = async () => ({ ok:false });
global.FileReader = function(){};
global.window = global;

const sandbox = { module:{exports:{}} };
const fn = new Function('document','fetch','FileReader','window',
  js + '\nreturn {computeDaily,bandFor,distributionOf,percentileOf,calibratedBands,verdictOf};');
const E = fn(global.document, global.fetch, global.FileReader, global);

const bars = JSON.parse(fs.readFileSync('xcheck_bars.json', 'utf8'));
const py   = JSON.parse(fs.readFileSync('xcheck_py.json', 'utf8'));

const jsSessions = E.computeDaily(bars, {});

let fails = 0;
function cmp(label, a, b, tol) {
  const ok = tol === undefined ? a === b : Math.abs(a - b) <= tol;
  if (!ok) { console.log(`  MISMATCH ${label}: py=${b} js=${a}`); fails++; }
  return ok;
}

if (jsSessions.length !== py.length) {
  console.log(`  MISMATCH session count: py=${py.length} js=${jsSessions.length}`);
  fails++;
}

const n = Math.min(jsSessions.length, py.length);
for (let i = 0; i < n; i++) {
  const j = jsSessions[i], p = py[i];
  cmp(`[${i}] date`, j.date, p.date);
  cmp(`[${i}] ratio`, j.ratio, p.ratio, 1e-9);
  cmp(`[${i}] regime`, j.regime, p.regime);
  cmp(`[${i}] n_high`, j.n_high, p.n_high);
  cmp(`[${i}] n_low`, j.n_low, p.n_low);
  cmp(`[${i}] n_counted`, j.n_counted, p.n_counted);
  cmp(`[${i}] adv`, j.adv, p.adv);
  cmp(`[${i}] dec`, j.dec, p.dec);
  cmp(`[${i}] upper`, j.upper_half, p.upper_half);
  cmp(`[${i}] lower`, j.lower_half, p.lower_half);
  cmp(`[${i}] days_in_regime`, j.days_in_regime, p.days_in_regime);
  // The engines use different dash glyphs for the "not enough history" case.
  const dash = s => s.replace(/[—–]/g, '-');
  cmp(`[${i}] slope_label`, dash(j.slope_label), dash(p.slope_label));
  cmp(`[${i}] verdict`, j.verdict.replace(/—/g,'-'), p.verdict);
  if (fails > 12) { console.log('  ...stopping after 12 mismatches'); break; }
}

console.log(`compared ${n} sessions across 13 fields each (${n*13} checks)`);
if (fails === 0) console.log('PASS  JavaScript and Python engines agree exactly');
else { console.log(`FAIL  ${fails} mismatches`); process.exit(1); }
