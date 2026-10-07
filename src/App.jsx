import React, { useState, useEffect } from 'react';

export default function HydroLinkApp() {
  const [activeTab, setActiveTab] = useState('controlRoom');
  const [dashboardData, setDashboardData] = useState([]);
  const [selectedStationId, setSelectedStationId] = useState('');
  const [stationReading, setStationReading] = useState(null);
  const [alertsData, setAlertsData] = useState([]);
  
  // State for interactive WhatsApp feedback simulation
  const [farmerInput, setFarmerInput] = useState('');
  const [farmerLang, setFarmerLang] = useState('Sepedi');
  const [feedbackLog, setFeedbackLog] = useState([
    { id: 1, farmer: 'Mmaetsho K.', report: 'River is near the lower bridge edge.', lang: 'Sepedi', impact: '+5 Trust Boost' }
  ]);
  const [feedbackStatus, setFeedbackStatus] = useState(null);

  const API_BASE = 'http://localhost:8000/api';

  // 1. Fetch Dashboard Feed Health & Alerts on Load
  useEffect(() => {
    async function fetchInitialData() {
      try {
        const dashRes = await fetch(`${API_BASE}/dashboard`);
        const dashJson = await dashRes.json();
        setDashboardData(dashJson);
        if (dashJson.length > 0) {
          setSelectedStationId(dashJson[0].station_id);
        }

        const alertRes = await fetch(`${API_BASE}/alerts`);
        const alertJson = await alertRes.json();
        setAlertsData(alertJson);
      } catch (err) {
        console.error("Failed to connect to FastAPI backend:", err);
      }
    }
    fetchInitialData();
  }, []);

  // 2. Fetch Detailed Station Readings when selectedStationId changes
  useEffect(() => {
    if (!selectedStationId) return;
    async function fetchStationDetails() {
      try {
        const res = await fetch(`${API_BASE}/readings?station_id=${selectedStationId}`);
        const data = await res.json();
        setStationReading(data);
      } catch (err) {
        console.error("Failed to fetch station readings:", err);
      }
    }
    fetchStationDetails();
  }, [selectedStationId]);

  // 3. Handle Farmer Feedback Submission (POST to Backend API)
  const handleFeedbackSubmit = async (e) => {
    e.preventDefault();
    if (!farmerInput) return;
    try {
      const response = await fetch(`${API_BASE}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          station_id: selectedStationId,
          report: farmerInput,
          lang: farmerLang
        })
      });
      const result = await response.json();
      
      const newReport = {
        id: feedbackLog.length + 1,
        farmer: result.farmer,
        report: result.report,
        lang: result.lang,
        impact: result.impact
      };
      setFeedbackLog([newReport, ...feedbackLog]);
      setFeedbackStatus(result.message);
      setFarmerInput('');
    } catch (err) {
      setFeedbackStatus("Failed to submit report to backend.");
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans p-6">
      {/* HEADER */}
      <header className="flex flex-col md:flex-row justify-between items-start md:items-center border-b border-slate-800 pb-6 mb-8">
        <div>
          <div className="flex items-center space-x-3">
            <span className="bg-emerald-500 text-slate-950 text-xs font-black px-2.5 py-1 rounded tracking-wide uppercase">
              IBM Z Datathon 2026 Finalist
            </span>
            <span className="text-xs text-slate-400 font-mono">Team BelovedHackers</span>
          </div>
          <h1 className="text-3xl font-black tracking-tight text-white mt-2">
            HydroLink SA <span className="text-emerald-400">Control Center</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Real-Time AI Trust Layer & Multi-Source Validation Dashboard (Connected to FastAPI).
          </p>
        </div>

        {/* NAVIGATION TABS */}
        <div className="mt-4 md:mt-0 flex space-x-2 bg-slate-900 p-1.5 rounded-lg border border-slate-800">
          <button 
            onClick={() => setActiveTab('controlRoom')}
            className={`px-4 py-2 rounded-md text-xs font-bold transition-all ${activeTab === 'controlRoom' ? 'bg-emerald-500 text-slate-950 shadow' : 'text-slate-400 hover:text-white'}`}
          >
            Municipal Dashboard
          </button>
          <button 
            onClick={() => setActiveTab('community')}
            className={`px-4 py-2 rounded-md text-xs font-bold transition-all ${activeTab === 'community' ? 'bg-emerald-500 text-slate-950 shadow' : 'text-slate-400 hover:text-white'}`}
          >
            WhatsApp & Alerts
          </button>
          <button 
            onClick={() => setActiveTab('audit')}
            className={`px-4 py-2 rounded-md text-xs font-bold transition-all ${activeTab === 'audit' ? 'bg-emerald-500 text-slate-950 shadow' : 'text-slate-400 hover:text-white'}`}
          >
            IBM Z Ledger
          </button>
        </div>
      </header>

      {/* TAB 1: MUNICIPAL CONTROL ROOM */}
      {activeTab === 'controlRoom' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            {/* Feed Health Overview (Dashboard API) */}
            <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl lg:col-span-1 space-y-4">
              <h3 className="text-sm font-bold text-white uppercase tracking-wider">Catchment Station Health</h3>
              <p className="text-xs text-slate-400">Fetched live from GET /api/dashboard</p>
              
              <div className="space-y-2">
                {dashboardData.map((st) => (
                  <div 
                    key={st.station_id}
                    onClick={() => setSelectedStationId(st.station_id)}
                    className={`p-3 rounded-lg border cursor-pointer transition-all ${selectedStationId === st.station_id ? 'bg-slate-800 border-emerald-500' : 'bg-slate-950 border-slate-800 hover:border-slate-700'}`}
                  >
                    <div className="flex justify-between items-center">
                      <span className="text-xs font-mono font-bold text-white">{st.station_id}</span>
                      <span className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase ${st.status === 'healthy' ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-rose-950 text-rose-300 border border-rose-800'}`}>
                        {st.status}
                      </span>
                    </div>
                    <p className="text-xs text-slate-300 mt-1">{st.name}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Deep-Dive Readings & Forecast Panel (Readings API) */}
            <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl lg:col-span-2 space-y-6">
              {stationReading ? (
                <div>
                  <div className="flex justify-between items-start border-b border-slate-800 pb-4 mb-4">
                    <div>
                      <span className="text-xs font-mono text-emerald-400">Station Analysis: {stationReading.station_id}</span>
                      <h2 className="text-xl font-bold text-white mt-1">{stationReading.name}</h2>
                    </div>
                    <div className={`px-3 py-1 rounded-full text-xs font-bold border ${stationReading.trust_score >= 80 ? 'bg-emerald-950 text-emerald-300 border-emerald-800' : 'bg-amber-950 text-amber-300 border-amber-800'}`}>
                      Trust Score: {stationReading.trust_score} / 100
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4 my-4">
                    <div className="bg-slate-950 p-4 rounded-lg border border-slate-800">
                      <span className="text-xs text-slate-400">Current Reading</span>
                      <p className="text-2xl font-black text-white mt-1">{stationReading.current_value} m</p>
                      <span className="text-[10px] text-slate-500 font-mono">Freshness & Plausibility Verified</span>
                    </div>
                    <div className="bg-slate-950 p-4 rounded-lg border border-slate-800">
                      <span className="text-xs text-slate-400">Short-Term Forecast (Next 24h)</span>
                      <p className="text-2xl font-black text-emerald-400 mt-1">{stationReading.forecast.predicted_level} m</p>
                      <span className="text-[10px] text-slate-500 font-mono">Confidence Interval: {stationReading.forecast.confidence_interval}</span>
                    </div>
                  </div>

                  <div className="bg-slate-950 p-4 rounded-lg border border-slate-800 space-y-2 mt-4">
                    <h4 className="text-xs font-bold text-slate-300 uppercase">AI Explainability Audit</h4>
                    <p className="text-xs text-slate-400 italic">"{stationReading.anomalies_flagged}"</p>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-slate-500">Loading station telemetry from backend...</p>
              )}

              {/* Simulated Farmer Feedback Form (Feedback API) */}
              <div className="border-t border-slate-800 pt-6 mt-6">
                <h3 className="text-sm font-bold text-white mb-2">Simulate Farmer WhatsApp Input (POST /api/feedback)</h3>
                <p className="text-xs text-slate-400 mb-4">Send a mock report to your FastAPI backend to test trust recalibration.</p>
                
                <form onSubmit={handleFeedbackSubmit} className="space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    <input 
                      type="text" 
                      placeholder="e.g. Water is rising fast near bridge"
                      value={farmerInput}
                      onChange={(e) => setFarmerInput(e.target.value)}
                      className="bg-slate-950 border border-slate-800 rounded px-3 py-2 text-xs text-white md:col-span-2 focus:outline-none focus:border-emerald-500"
                    />
                    <select 
                      value={farmerLang} 
                      onChange={(e) => setFarmerLang(e.target.value)}
                      className="bg-slate-950 border border-slate-800 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-emerald-500"
                    >
                      <option value="Sepedi">Sepedi</option>
                      <option value="isiZulu">isiZulu</option>
                      <option value="Afrikaans">Afrikaans</option>
                    </select>
                  </div>
                  <button type="submit" className="px-4 py-2 bg-emerald-500 text-slate-950 rounded text-xs font-bold hover:bg-emerald-400 transition-colors">
                    Send WhatsApp Report to API
                  </button>
                  {feedbackStatus && <p className="text-xs text-emerald-400 font-mono mt-2">{feedbackStatus}</p>}
                </form>

                {/* Feedback Log Feed */}
                <div className="mt-4 space-y-2">
                  <h4 className="text-[11px] font-bold text-slate-400 uppercase">Recent Community Cross-Checks:</h4>
                  {feedbackLog.map((log) => (
                    <div key={log.id} className="bg-slate-950 border border-slate-800/60 p-2.5 rounded text-xs flex justify-between items-center">
                      <span className="text-slate-300 italic">"{log.report}" ({log.lang})</span>
                      <span className="text-emerald-400 font-mono text-[10px]">{log.impact}</span>
                    </div>
                  ))}
                </div>
              </div>

            </div>
          </div>
        </div>
      )}

      {/* TAB 2: WHATSAPP ALERTS (Alerts API) */}
      {activeTab === 'community' && (
        <div className="space-y-6">
          <div className="bg-slate-900 border border-slate-800 p-6 rounded-xl">
            <h3 className="text-lg font-bold text-white mb-1">Multilingual Community Alerts (GET /api/alerts)</h3>
            <p className="text-xs text-slate-400 mb-6">Real-time plain-language warnings fetched directly from your backend.</p>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {alertsData.map((al, index) => (
                <div key={index} className="bg-slate-950 border border-slate-800 p-5 rounded-xl space-y-3 relative overflow-hidden">
                  <div className="absolute top-0 left-0 w-1.5 h-full bg-emerald-500"></div>
                  <div className="flex justify-between items-center">
                    <span className="text-[10px] font-mono bg-slate-800 px-2 py-0.5 rounded text-emerald-400 uppercase">{al.language}</span>
                    <span className="text-[10px] text-slate-500 font-mono">{al.station_id}</span>
                  </div>
                  <p className="text-xs text-slate-200 font-medium italic">"{al.message}"</p>
                  <div className="text-[10px] text-emerald-400 font-bold pt-2 border-t border-slate-900">
                    Trust Rating: {al.trust_score} / 100 ({al.status})
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: IBM Z AUDIT LEDGER */}
      {activeTab === 'audit' && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
          <div className="border-b border-slate-800 pb-4">
            <h3 className="text-lg font-bold text-white">Cryptographic Transaction & Decision Log (IBM Z Simulation)</h3>
            <p className="text-xs text-slate-400">Tamper-proof infrastructure ledger recording all automated validation events and trust-gated decisions.</p>
          </div>
          
          <div className="space-y-3 font-mono text-xs">
            <div className="bg-slate-950 p-3 rounded border border-slate-800 flex justify-between items-center">
              <div>
                <span className="text-emerald-400">[TIMESTAMP: 2026-10-06 18:00:12 SAST]</span>
                <p className="text-slate-300 mt-1">EVENT: Ingested DWS Station LMP-SD-01 &bull; Z-Score: 0.4 &bull; Trust Score: 88 &bull; Feed Healthy</p>
              </div>
              <span className="text-[10px] bg-emerald-950 text-emerald-300 px-2 py-1 rounded border border-emerald-800">HASH_VERIFIED</span>
            </div>
            
            <div className="bg-slate-950 p-3 rounded border border-slate-800 flex justify-between items-center">
              <div>
                <span className="text-amber-400">[TIMESTAMP: 2026-10-06 17:45:00 SAST]</span>
                <p className="text-slate-300 mt-1">EVENT: Anomaly Triggered LMP-CR-04 &bull; Value deviated 4.1 std devs &bull; Trust-Gated Alert Withheld</p>
              </div>
              <span className="text-[10px] bg-amber-950 text-amber-300 px-2 py-1 rounded border border-amber-800">HOLD_FOR_REVIEW</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}