import React, { useState } from 'react';

/* Real photos (Unsplash). If one fails to load, a themed gradient shows instead.
   For production, download them into /public/images and swap the URLs. */
const IMG = {
  hero: 'https://images.unsplash.com/photo-1439066615861-d1af74d74000?auto=format&fit=crop&w=1600&q=80',
  weir: 'https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=800&q=80',
  river: 'https://images.unsplash.com/photo-1473448912268-2022ce9509d8?auto=format&fit=crop&w=800&q=80',
  farm: 'https://images.unsplash.com/photo-1500937386664-56d1dfef3854?auto=format&fit=crop&w=1000&q=80',
};

const css = `
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=DM+Sans:wght@400;500;700&display=swap');
.hl{
  --night:#06171D; --deep:#0C2A33; --panel:#0F333D; --line:#1D4A56;
  --aqua:#37D4C0; --ochre:#F0A93B; --clay:#E0525F; --mist:#E4F2F0; --muted:#8DB3B8;
  font-family:'DM Sans',system-ui,sans-serif; color:var(--mist);
  background:
    radial-gradient(900px 500px at 85% -10%, rgba(55,212,192,.16), transparent 60%),
    radial-gradient(700px 400px at -10% 30%, rgba(240,169,59,.10), transparent 60%),
    var(--night);
  min-height:100vh;
}
.hl h1,.hl h2,.hl h3{font-family:'Bricolage Grotesque',sans-serif;letter-spacing:-.02em}
.hl-hero{position:relative;border-radius:28px;overflow:hidden;min-height:340px;display:flex;align-items:flex-end;border:1px solid var(--line)}
.hl-hero img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.hl-hero::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(6,23,29,.15) 0%,rgba(6,23,29,.92) 85%)}
.hl-hero>div{position:relative;z-index:1;padding:32px;width:100%}
.hl-fallback{background:linear-gradient(135deg,#0C2A33,#1B6F73 60%,#37D4C0)}
.hl-card{background:linear-gradient(180deg,var(--panel),var(--deep));border:1px solid var(--line);border-radius:22px}
.hl-chip{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 12px;font-size:12px;font-weight:700}
.hl-ok{background:rgba(55,212,192,.14);color:var(--aqua);border:1px solid rgba(55,212,192,.4)}
.hl-warn{background:rgba(240,169,59,.14);color:var(--ochre);border:1px solid rgba(240,169,59,.4)}
.hl-bad{background:rgba(224,82,95,.14);color:#FF8D97;border:1px solid rgba(224,82,95,.45)}
.hl-tab{padding:10px 18px;border-radius:999px;font-size:13px;font-weight:700;color:var(--muted);transition:.2s}
.hl-tab:hover{color:var(--mist)}
.hl-tab[data-on="true"]{background:linear-gradient(135deg,var(--aqua),#7BE8D8);color:#04262B;box-shadow:0 6px 24px rgba(55,212,192,.35)}
.hl-station{display:flex;gap:12px;align-items:center;padding:10px;border-radius:16px;border:1px solid var(--line);background:rgba(6,23,29,.5);cursor:pointer;transition:.2s;text-align:left;width:100%}
.hl-station:hover{border-color:var(--aqua)}
.hl-station[data-on="true"]{border-color:var(--aqua);background:rgba(55,212,192,.08);box-shadow:inset 3px 0 0 var(--aqua)}
.hl-thumb{width:56px;height:56px;border-radius:12px;object-fit:cover;flex:none}
.hl-stat{background:rgba(6,23,29,.6);border:1px solid var(--line);border-radius:18px;padding:18px}
.hl-input{background:rgba(6,23,29,.7);border:1px solid var(--line);border-radius:14px;padding:12px 14px;font-size:14px;color:var(--mist);width:100%}
.hl-input:focus{outline:2px solid var(--aqua);outline-offset:1px}
.hl-btn{background:linear-gradient(135deg,var(--ochre),#FFC96B);color:#2B1A00;font-weight:800;border-radius:14px;padding:12px 20px;font-size:14px;transition:.2s}
.hl-btn:hover{transform:translateY(-1px);box-shadow:0 8px 24px rgba(240,169,59,.35)}
.hl-btn:focus-visible,.hl-tab:focus-visible,.hl-station:focus-visible{outline:2px solid var(--aqua);outline-offset:2px}
.hl-bubble{background:#0B4A3F;border:1px solid #14705E;border-radius:18px 18px 18px 4px;padding:14px 16px}
.hl-rise{animation:hlrise .7s ease both}
@keyframes hlrise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.hl-rise{animation:none}.hl *{transition:none!important}}
`;

function Photo({ src, alt, className = '', style }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <div className={`hl-fallback ${className}`} style={style} role="img" aria-label={alt} />;
  return <img src={src} alt={alt} className={className} style={style} loading="lazy" onError={() => setFailed(true)} />;
}

function TrustRing({ score }) {
  const r = 34, c = 2 * Math.PI * r;
  const color = score >= 80 ? '#37D4C0' : score >= 60 ? '#F0A93B' : '#E0525F';
  return (
    <svg width="88" height="88" viewBox="0 0 88 88" role="img" aria-label={`Trust score ${score} out of 100`}>
      <circle cx="44" cy="44" r={r} fill="none" stroke="#1D4A56" strokeWidth="8" />
      <circle cx="44" cy="44" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
        strokeDasharray={`${(score / 100) * c} ${c}`} transform="rotate(-90 44 44)" />
      <text x="44" y="49" textAnchor="middle" fontSize="20" fontWeight="800" fill="#E4F2F0" fontFamily="Bricolage Grotesque">{score}</text>
    </svg>
  );
}

export default function HydroLinkApp() {
  const [activeTab, setActiveTab] = useState('controlRoom');
  const [selectedStationId, setSelectedStationId] = useState('LMP-SD-01');

  // Local Mock Database for Instant Frontend Demo
  const dashboardData = [
    {
      station_id: "LMP-SD-01",
      name: "Sand River Upstream Weir",
      catchment: "Limpopo (Sand/Crocodile)",
      trust_score: 88,
      current_value: 4.2,
      expected_range: "3.9m - 4.4m",
      status: "healthy",
      image: IMG.weir,
      forecast: { predicted_level: 4.3, confidence_interval: "± 0.2m" },
      anomalies_flagged: "Normal behavior. 0.4 standard deviations from baseline. Rainfall verified via SAWS."
    },
    {
      station_id: "LMP-CR-04",
      name: "Crocodile River Main Station",
      catchment: "Limpopo (Sand/Crocodile)",
      trust_score: 42,
      current_value: 6.1,
      expected_range: "2.1m - 2.5m",
      status: "missing",
      image: IMG.river,
      forecast: { predicted_level: 2.3, confidence_interval: "± 0.5m" },
      anomalies_flagged: "Anomaly Triggered: Stale/Spike detected (4.1 std deviations). Trust-gated alert withheld to prevent false panic."
    }
  ];

  const alertsData = [
    { station_id: "LMP-SD-01", language: "Sepedi", message: "Go na le mohlodi wa meetsi a mantsi mo nokeng ya Sand. Tshedimosetso e netefaditswe.", trust_score: 88, status: "Caution" },
    { station_id: "LMP-CR-04", language: "isiZulu", message: "Amanzi asezingeni eliphezulu endaweni yaseCrocodile. Qaphela ngaphambi kokuwela.", trust_score: 42, status: "Review Required" },
    { station_id: "LMP-SD-01", language: "Afrikaans", message: "Sandrivier vlakte stabiel. Geen direkte oorstromingsrisiko nie.", trust_score: 88, status: "Normal" }
  ];

  // State for interactive WhatsApp feedback simulation
  const [farmerInput, setFarmerInput] = useState('');
  const [farmerLang, setFarmerLang] = useState('Sepedi');
  const [feedbackLog, setFeedbackLog] = useState([
    { id: 1, farmer: 'Mmaetsho K.', report: 'River is near the lower bridge edge.', lang: 'Sepedi', impact: '+5 Trust Boost' }
  ]);
  const [feedbackStatus, setFeedbackStatus] = useState(null);

  const activeStation = dashboardData.find(s => s.station_id === selectedStationId) || dashboardData[0];

  const handleFeedbackSubmit = (e) => {
    e.preventDefault();
    if (!farmerInput) return;
    const newReport = {
      id: feedbackLog.length + 1,
      farmer: 'Smallholder Farmer (Simulated)',
      report: farmerInput,
      lang: farmerLang,
      impact: '+5 Trust Boost Applied'
    };
    setFeedbackLog([newReport, ...feedbackLog]);
    setFeedbackStatus("Successfully simulated WhatsApp community cross-check report!");
    setFarmerInput('');
  };

  const statusChip = (s) => (s === 'healthy' ? 'hl-ok' : 'hl-bad');
  const alertChip = (s) => (s === 'Normal' ? 'hl-ok' : s === 'Caution' ? 'hl-warn' : 'hl-bad');
  const tabs = [
    ['controlRoom', 'Municipal dashboard'],
    ['community', 'WhatsApp & alerts'],
    ['audit', '🔒 IBM Z ledger'],
  ];

  return (
    <div className="hl p-4 md:p-8">
      <style>{css}</style>

      {/* HERO */}
      <header className="hl-hero hl-rise mb-6">
        <Photo src={IMG.hero} alt="Calm river water at dusk" />
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6">
          <div className="max-w-2xl">
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <span className="hl-chip hl-warn">IBM Z Datathon 2026 finalist</span>
              <span className="hl-chip hl-ok">Team TheLocalDev</span>
            </div>
            <h1 className="text-4xl md:text-6xl font-extrabold text-white leading-[1.02]">
              HydroLink SA: know which water data to trust
            </h1>
            <p className="mt-3 text-sm md:text-base" style={{ color: '#C9E2E0' }}>
              A real-time AI trust layer that scores every river and dam reading, and warns people only when the data holds up.
            </p>
          </div>
          <nav className="flex gap-1 p-1.5 rounded-full border self-start md:self-end" style={{ background: 'rgba(6,23,29,.75)', borderColor: 'var(--line)', backdropFilter: 'blur(8px)' }}>
            {tabs.map(([id, label]) => (
              <button key={id} className="hl-tab" data-on={activeTab === id} onClick={() => setActiveTab(id)}>
                {label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {/* TAB 1: MUNICIPAL CONTROL ROOM */}
      {activeTab === 'controlRoom' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 hl-rise">
          {/* Station list */}
          <div className="hl-card p-6 lg:col-span-1 space-y-4">
            <div>
              <h3 className="text-xl font-bold text-white">Catchment station health</h3>
              <p className="text-sm mt-1" style={{ color: 'var(--muted)' }}>Pick a station to see its trust score and 24-hour forecast.</p>
            </div>
            <div className="space-y-3">
              {dashboardData.map((st) => (
                <button key={st.station_id} className="hl-station" data-on={selectedStationId === st.station_id} onClick={() => setSelectedStationId(st.station_id)}>
                  <Photo src={st.image} alt={st.name} className="hl-thumb" style={{ width: 56, height: 56 }} />
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-center gap-2">
                      <span className="text-sm font-bold text-white">{st.station_id}</span>
                      <span className={`hl-chip ${statusChip(st.status)}`}>{st.status}</span>
                    </div>
                    <p className="text-xs mt-1 truncate" style={{ color: 'var(--muted)' }}>{st.name}</p>
                  </div>
                </button>
              ))}
            </div>
            <Photo src={IMG.farm} alt="Farmland in the Limpopo region" className="w-full" style={{ height: 150, objectFit: 'cover', borderRadius: 16 }} />
            <p className="text-xs" style={{ color: 'var(--muted)' }}>Built for smallholder farmers and rural communities who need earlier, more trustworthy warnings.</p>
          </div>

          {/* Deep-dive */}
          <div className="hl-card p-6 lg:col-span-2 space-y-6">
            <div className="flex justify-between items-center gap-4 border-b pb-5" style={{ borderColor: 'var(--line)' }}>
              <div>
                <span className="text-sm font-bold" style={{ color: 'var(--aqua)' }}>Station analysis: {activeStation.station_id}</span>
                <h2 className="text-2xl md:text-3xl font-extrabold text-white mt-1">{activeStation.name}</h2>
                <p className="text-xs mt-1" style={{ color: 'var(--muted)' }}>{activeStation.catchment}</p>
              </div>
              <div className="text-center flex-none">
                <TrustRing score={activeStation.trust_score} />
                <span className="text-xs" style={{ color: 'var(--muted)' }}>Trust score</span>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="hl-stat">
                <span className="text-sm" style={{ color: 'var(--muted)' }}>Current reading</span>
                <p className="text-4xl font-extrabold text-white mt-1" style={{ fontFamily: 'Bricolage Grotesque' }}>{activeStation.current_value} m</p>
                <span className="text-xs" style={{ color: 'var(--muted)' }}>Expected {activeStation.expected_range}</span>
              </div>
              <div className="hl-stat" style={{ borderColor: 'rgba(55,212,192,.45)' }}>
                <span className="text-sm" style={{ color: 'var(--muted)' }}>Short-term forecast (next 24h)</span>
                <p className="text-4xl font-extrabold mt-1" style={{ color: 'var(--aqua)', fontFamily: 'Bricolage Grotesque' }}>{activeStation.forecast.predicted_level} m</p>
                <span className="text-xs" style={{ color: 'var(--muted)' }}>Confidence interval {activeStation.forecast.confidence_interval}</span>
              </div>
            </div>

            <div className="hl-stat" style={{ borderLeft: `4px solid ${activeStation.status === 'healthy' ? 'var(--aqua)' : 'var(--clay)'}` }}>
              <h4 className="text-sm font-bold text-white">Why the AI flagged this</h4>
              <p className="text-sm mt-1 italic" style={{ color: '#B7D3D2' }}>"{activeStation.anomalies_flagged}"</p>
            </div>

            {/* Farmer feedback */}
            <div className="border-t pt-6" style={{ borderColor: 'var(--line)' }}>
              <h3 className="text-lg font-bold text-white">Simulate a farmer's WhatsApp report</h3>
              <p className="text-sm mb-4" style={{ color: 'var(--muted)' }}>Send a mock report to see how community input recalibrates trust.</p>

              <form onSubmit={handleFeedbackSubmit} className="space-y-3">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <input
                    type="text"
                    placeholder="e.g. Water is rising fast near bridge"
                    value={farmerInput}
                    onChange={(e) => setFarmerInput(e.target.value)}
                    className="hl-input md:col-span-2"
                  />
                  <select value={farmerLang} onChange={(e) => setFarmerLang(e.target.value)} className="hl-input">
                    <option value="Sepedi">Sepedi</option>
                    <option value="isiZulu">isiZulu</option>
                    <option value="Afrikaans">Afrikaans</option>
                  </select>
                </div>
                <button type="submit" className="hl-btn">Send WhatsApp report</button>
                {feedbackStatus && <p className="text-sm font-medium" style={{ color: 'var(--aqua)' }}>{feedbackStatus}</p>}
              </form>

              <div className="mt-5 space-y-2">
                <h4 className="text-sm font-bold" style={{ color: 'var(--muted)' }}>Recent community cross-checks</h4>
                {feedbackLog.map((log) => (
                  <div key={log.id} className="hl-bubble flex justify-between items-center gap-3 text-sm">
                    <span className="italic" style={{ color: '#D8F3EC' }}>"{log.report}" ({log.lang})</span>
                    <span className="hl-chip hl-ok flex-none">{log.impact}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: WHATSAPP ALERTS */}
      {activeTab === 'community' && (
        <div className="hl-card p-6 md:p-8 hl-rise">
          <h3 className="text-2xl font-extrabold text-white">Alerts in the languages people speak</h3>
          <p className="text-sm mb-6 mt-1" style={{ color: 'var(--muted)' }}>Plain-language warnings sent by WhatsApp to rural communities and farmers in Limpopo.</p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {alertsData.map((al, index) => (
              <div key={index} className="hl-stat flex flex-col gap-4" style={{ borderTop: `4px solid ${al.status === 'Normal' ? 'var(--aqua)' : al.status === 'Caution' ? 'var(--ochre)' : 'var(--clay)'}` }}>
                <div className="flex justify-between items-center">
                  <span className="hl-chip hl-ok">{al.language}</span>
                  <span className="text-xs font-bold" style={{ color: 'var(--muted)' }}>{al.station_id}</span>
                </div>
                <div className="hl-bubble text-sm italic" style={{ color: '#D8F3EC' }}>"{al.message}"</div>
                <div className="flex justify-between items-center mt-auto pt-3 border-t" style={{ borderColor: 'var(--line)' }}>
                  <span className="text-xs" style={{ color: 'var(--muted)' }}>Trust {al.trust_score} / 100</span>
                  <span className={`hl-chip ${alertChip(al.status)}`}>{al.status}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 3: IBM Z AUDIT LEDGER */}
      {activeTab === 'audit' && (
        <div className="hl-card p-6 md:p-8 space-y-5 hl-rise">
          <div className="border-b pb-4" style={{ borderColor: 'var(--line)' }}>
            <h3 className="text-2xl font-extrabold text-white">Decision log (IBM Z simulation)</h3>
            <p className="text-sm mt-1" style={{ color: 'var(--muted)' }}>A tamper-proof record of every validation event and trust-gated decision.</p>
          </div>

          <div className="space-y-3">
            <div className="hl-stat flex justify-between items-center gap-4" style={{ borderLeft: '4px solid var(--aqua)' }}>
              <div>
                <span className="text-sm font-bold" style={{ color: 'var(--aqua)' }}>2026-10-06 18:00:12 SAST</span>
                <p className="text-sm mt-1" style={{ color: '#C9E2E0' }}>Ingested DWS station LMP-SD-01 &bull; Z-score 0.4 &bull; Trust score 88 &bull; Feed healthy</p>
              </div>
              <span className="hl-chip hl-ok flex-none">Hash verified</span>
            </div>

            <div className="hl-stat flex justify-between items-center gap-4" style={{ borderLeft: '4px solid var(--ochre)' }}>
              <div>
                <span className="text-sm font-bold" style={{ color: 'var(--ochre)' }}>2026-10-06 17:45:00 SAST</span>
                <p className="text-sm mt-1" style={{ color: '#C9E2E0' }}>Anomaly on LMP-CR-04 &bull; Value deviated 4.1 std devs &bull; Trust-gated alert withheld</p>
              </div>
              <span className="hl-chip hl-warn flex-none">Hold for review</span>
            </div>
          </div>
        </div>
      )}

      <footer className="text-center text-xs mt-8" style={{ color: 'var(--muted)' }}>
        HydroLink SA &bull; Built by TheLocalDev
      </footer>
    </div>
  );
}
