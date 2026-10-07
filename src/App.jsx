import { useEffect, useMemo, useState } from 'react';
import {
  Activity, ArrowDownRight, ArrowUpRight, Bell, CalendarDays, Check, ChevronDown,
  ChevronRight, CircleAlert, Clock3, Cpu, Droplets, FileText, FlaskConical, Gauge,
  LayoutDashboard, Map, Menu, Search, Send, ShieldCheck, Sparkles, Waves, X,
} from 'lucide-react';
import './App.css';

const API_BASE = 'http://localhost:8000/api';
const displayDate = new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date());

const navigation = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'network', label: 'Network Map', icon: Map },
  { id: 'monitoring', label: 'Monitoring', icon: Activity },
  { id: 'insights', label: 'AI Insight', icon: Sparkles },
  { id: 'quality', label: 'Water Quality', icon: FlaskConical },
  { id: 'forecast', label: 'Forecasting', icon: Waves },
  { id: 'devices', label: 'IoT Devices', icon: Cpu },
  { id: 'reports', label: 'Reports', icon: FileText },
];

function MetricCard({ label, value, unit, note, trend, direction = 'up', accent = 'green' }) {
  const TrendIcon = direction === 'down' ? ArrowDownRight : ArrowUpRight;
  return (
    <article className={`metric-card metric-${accent}`}>
      <div className="metric-copy">
        <div className="metric-label">{label}<span className="metric-link"><ArrowUpRight size={12} /></span></div>
        <div className="metric-value">{value}<span>{unit}</span></div>
        <div className={`metric-note ${trend ? `trend-${direction}` : ''}`}>
          {trend && <TrendIcon size={12} strokeWidth={2.4} />}{note}
        </div>
      </div>
      <div className="metric-spark" aria-hidden="true">
        <svg viewBox="0 0 116 54" preserveAspectRatio="none">
          <path d="M0 47 L18 40 L35 44 L52 30 L70 35 L88 16 L103 21 L116 4 L116 54 L0 54 Z" />
          <path d="M0 47 L18 40 L35 44 L52 30 L70 35 L88 16 L103 21 L116 4" />
          <circle cx="88" cy="16" r="3.5" />
        </svg>
      </div>
    </article>
  );
}

function StatusPill({ status }) {
  const healthy = status?.toLowerCase() === 'healthy';
  return <span className={`status-pill ${healthy ? 'is-healthy' : 'is-review'}`}><span />{status || 'unknown'}</span>;
}

export default function HydroLinkApp() {
  const [activeTab, setActiveTab] = useState('overview');
  const [dashboardData, setDashboardData] = useState([]);
  const [selectedStationId, setSelectedStationId] = useState('');
  const [stationReading, setStationReading] = useState(null);
  const [alertsData, setAlertsData] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);
  const [farmerInput, setFarmerInput] = useState('');
  const [farmerLang, setFarmerLang] = useState('Sepedi');
  const [feedbackStatus, setFeedbackStatus] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    async function fetchAppData() {
      setIsLoading(true);
      setErrorMsg(null);
      try {
        const [dashboardResponse, alertsResponse] = await Promise.all([
          fetch(`${API_BASE}/dashboard`), fetch(`${API_BASE}/alerts`),
        ]);
        if (!dashboardResponse.ok || !alertsResponse.ok) throw new Error('The operations feed is temporarily unavailable.');
        const [stations, alerts] = await Promise.all([dashboardResponse.json(), alertsResponse.json()]);
        setDashboardData(stations);
        setAlertsData(alerts);
        if (stations.length) setSelectedStationId(stations[0].station_id);
      } catch (error) {
        setErrorMsg(error.message || 'Could not connect to the operations feed.');
      } finally {
        setIsLoading(false);
      }
    }
    fetchAppData();
  }, []);

  useEffect(() => {
    if (!selectedStationId) return;
    async function fetchStationDetails() {
      try {
        const response = await fetch(`${API_BASE}/readings?station_id=${encodeURIComponent(selectedStationId)}`);
        if (!response.ok) throw new Error('Station details are unavailable.');
        setStationReading(await response.json());
      } catch (error) {
        console.error(error);
      }
    }
    fetchStationDetails();
  }, [selectedStationId]);

  const selectedStation = dashboardData.find((station) => station.station_id === selectedStationId);
  const healthyStations = dashboardData.filter((station) => station.status === 'healthy').length;
  const averageTrust = dashboardData.length
    ? Math.round(dashboardData.reduce((total, station) => total + station.trust_score, 0) / dashboardData.length)
    : 0;
  const filteredStations = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return dashboardData;
    return dashboardData.filter((station) => `${station.name} ${station.station_id} ${station.catchment}`.toLowerCase().includes(query));
  }, [dashboardData, searchQuery]);
  const selectedPage = navigation.find((item) => item.id === activeTab)?.label || 'Overview';
  const reviewAlerts = alertsData.filter((alert) => alert.status?.toLowerCase() !== 'normal');

  async function handleFeedbackSubmit(event) {
    event.preventDefault();
    if (!farmerInput.trim()) return;
    try {
      const response = await fetch(`${API_BASE}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ station_id: selectedStationId, report: farmerInput.trim(), lang: farmerLang }),
      });
      if (!response.ok) throw new Error('Report could not be sent.');
      const result = await response.json();
      setFeedbackStatus(result.message || 'Field report added to the community cross-check.');
      setFarmerInput('');
    } catch (error) {
      setFeedbackStatus(error.message || 'Failed to transmit the report.');
    }
  }

  function selectTab(tab) {
    setActiveTab(tab);
    setMobileNavOpen(false);
    setNotificationsOpen(false);
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar glass-panel ${mobileNavOpen ? 'sidebar-open' : ''}`}>
        <div className="brand-lockup"><span className="brand-mark"><Droplets size={19} strokeWidth={2.1} /></span><span>HydroLink</span></div>
        <div className="sidebar-label">Workspace</div>
        <nav className="side-nav" aria-label="Main navigation">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-item ${activeTab === id ? 'active' : ''}`} onClick={() => selectTab(id)}>
              <Icon size={17} strokeWidth={1.8} /><span>{label}</span>
              {id === 'reports' && reviewAlerts.length > 0 && <span className="nav-count">{reviewAlerts.length}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <button className={`ledger-link ${activeTab === 'ledger' ? 'active' : ''}`} onClick={() => selectTab('ledger')}><ShieldCheck size={17} strokeWidth={1.8} /><span>Trust Ledger</span><ChevronRight size={14} /></button>
        <div className="sidebar-status"><span className={`status-dot ${errorMsg ? 'offline' : ''}`} />{errorMsg ? 'Feed disconnected' : 'Systems operational'}</div>
        <button className="summarize-button" onClick={() => selectTab('insights')}><Sparkles size={15} />Summarize with AI</button>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <button className="mobile-menu icon-button" aria-label="Toggle navigation" onClick={() => setMobileNavOpen((open) => !open)}>{mobileNavOpen ? <X size={19} /> : <Menu size={19} />}</button>
          <div className="page-heading"><span className="heading-icon"><LayoutDashboard size={19} /></span><h1>{selectedPage}</h1></div>
          <div className="topbar-tools">
            <label className="search-box"><span className="sr-only">Search stations</span><input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Search stations..." /><Search size={17} /></label>
            <div className="date-chip"><CalendarDays size={15} /><span>{displayDate}</span><ChevronDown size={13} /></div>
            <div className="notification-wrap">
              <button className={`icon-button notification-button ${notificationsOpen ? 'pressed' : ''}`} aria-label="Notifications" onClick={() => setNotificationsOpen((open) => !open)}><Bell size={17} />{reviewAlerts.length > 0 && <span className="notification-dot" />}</button>
              {notificationsOpen && <div className="notification-popover"><strong>Recent alerts</strong>{alertsData.length ? alertsData.slice(0, 3).map((alert, index) => <div className="popover-alert" key={`${alert.station_id}-${index}`}><span className="alert-dot" /><span>{alert.message}</span></div>) : <p>No new alerts.</p>}<button onClick={() => selectTab('reports')}>Open reports <ArrowUpRight size={13} /></button></div>}
            </div>
            <button className="profile-chip" onClick={() => selectTab('ledger')} aria-label="Open operations ledger"><span className="profile-avatar">HL</span><span className="profile-copy"><strong>Operations Desk</strong><small>HydroLink SA</small></span><ChevronDown size={13} /></button>
          </div>
        </header>

        <div className="page-content">
          {errorMsg && <div className="error-banner"><CircleAlert size={16} /><span>{errorMsg}</span><span className="error-hint">Check the API at localhost:8000</span></div>}
          {isLoading ? <div className="loading-state"><span className="loading-ring" /><p>Loading station telemetry</p></div> : activeTab === 'overview' ? (
            <>
              <section className="metric-grid" aria-label="Operations summary">
                <MetricCard label="River level" value={stationReading?.current_value ?? '--'} unit="m" note={stationReading?.expected_range ? `Expected ${stationReading.expected_range}` : 'Awaiting station data'} trend={stationReading?.status === 'healthy' ? 'Within expected range' : null} />
                <MetricCard label="Average trust score" value={averageTrust || '--'} unit="%" note={`${healthyStations} of ${dashboardData.length} stations healthy`} trend="Validated telemetry" accent="coral" direction="down" />
                <MetricCard label="Stations reporting" value={dashboardData.length.toString().padStart(2, '0')} unit="" note={`${reviewAlerts.length} alerts need review`} trend="Live network status" />
              </section>

              <section className="overview-grid">
                <article className="feature-card">
                  <div className="feature-photo" /><div className="feature-overlay" />
                  <div className="feature-topline"><span><Waves size={12} />Catchment watch</span><StatusPill status={selectedStation?.status} /></div>
                  <div className="feature-copy"><span className="eyebrow">{selectedStation?.station_id || 'Live network'}</span><h2>{selectedStation?.name || 'River monitoring'}</h2><p>{selectedStation?.catchment || 'Catchment data will appear when stations connect.'}</p><div className="feature-reading"><strong>{stationReading?.current_value ?? '--'}<small> m</small></strong><span>current water level</span></div><button className="feature-action" onClick={() => selectTab('monitoring')}>View station analysis <ArrowUpRight size={14} /></button></div>
                </article>

                <article className="panel timeline-panel">
                  <div className="panel-heading"><div><span className="eyebrow">Live operations</span><h2>Timeline suggestion</h2></div><button className="text-action" onClick={() => selectTab('insights')}>View analysis <ChevronRight size={14} /></button></div>
                  <div className="timeline-list">
                    <div className="timeline-item"><span className="timeline-marker marker-red" /><div><strong>Station reading received</strong><p>{stationReading ? `${stationReading.current_value} m recorded at ${stationReading.station_id}` : 'Waiting for the next station reading'}</p></div><time>Now</time></div>
                    <div className="timeline-item"><span className="timeline-marker" /><div><strong>Baseline comparison complete</strong><p>{stationReading?.expected_range ? `Expected range is ${stationReading.expected_range}` : 'Checking station range'}</p></div><time>1m</time></div>
                    <div className="timeline-item"><span className="timeline-marker" /><div><strong>Forecast recalculated</strong><p>{stationReading ? `Next 24 hours: ${stationReading.forecast.predicted_level} m (${stationReading.forecast.confidence_interval})` : 'Forecast will appear with station data'}</p></div><time>4m</time></div>
                    <div className="timeline-item"><span className="timeline-marker" /><div><strong>Trust gate evaluated</strong><p>{stationReading?.anomalies_flagged || 'No anomaly details reported'}</p></div><time>6m</time></div>
                  </div>
                </article>

                <aside className="right-rail">
                  <article className="panel health-panel"><div className="panel-heading compact"><h2>Health score</h2><button className="text-action" onClick={() => selectTab('insights')}>Details <ChevronRight size={13} /></button></div><div className="gauge-wrap"><div className="gauge" style={{ '--gauge-score': `${stationReading?.trust_score ?? averageTrust}%` }}><div className="gauge-inner"><strong>{stationReading?.trust_score ?? averageTrust}%</strong><span>trust</span></div></div></div><div className="gauge-caption"><span className="status-dot" />{(stationReading?.trust_score ?? averageTrust) >= 80 ? 'Strong confidence' : 'Review recommended'}</div></article>
                  <article className="panel quality-panel"><div className="panel-heading compact"><h2>Water integrity</h2><button className="text-action" onClick={() => selectTab('quality')}>Details <ChevronRight size={13} /></button></div><div className="quality-stats"><div><span>Expected range</span><strong>{stationReading?.expected_range || '--'}</strong><small>station baseline</small></div><div><span>Forecast</span><strong>{stationReading?.forecast?.predicted_level ?? '--'}<small> m</small></strong><small>{stationReading?.forecast?.confidence_interval || 'confidence pending'}</small></div></div></article>
                </aside>
              </section>

              <section className="bottom-grid">
                <article className="panel alerts-panel"><div className="panel-heading"><div><h2>Smart alerts <span className="heading-count">{alertsData.length}</span></h2></div><button className="text-action" onClick={() => selectTab('reports')}>View all <ChevronRight size={14} /></button></div><div className="alert-list">{alertsData.slice(0, 3).map((alert, index) => <div className="alert-row" key={`${alert.station_id}-${index}`}><span className={`alert-symbol ${alert.status?.toLowerCase() === 'normal' ? 'info' : index === 1 ? 'warning' : 'critical'}`}><CircleAlert size={13} /></span><div><strong>{alert.message}</strong><span>{alert.station_id} · {alert.language}</span></div><span className={`alert-severity ${alert.status?.toLowerCase() === 'normal' ? 'severity-info' : index === 1 ? 'severity-warning' : 'severity-critical'}`}>{alert.status}</span></div>)}{!alertsData.length && <p className="empty-message">No active alerts.</p>}</div></article>
                <article className="panel station-panel"><div className="panel-heading"><div><h2>Station trust</h2></div><button className="text-action" onClick={() => selectTab('monitoring')}>All stations <ChevronRight size={14} /></button></div><div className="station-trust-list">{filteredStations.slice(0, 4).map((station) => <button key={station.station_id} className={`trust-row ${station.station_id === selectedStationId ? 'selected' : ''}`} onClick={() => setSelectedStationId(station.station_id)}><span className="trust-station"><span className={`mini-status ${station.status === 'healthy' ? '' : 'review'}`} /><span><strong>{station.name}</strong><small>{station.station_id}</small></span></span><span className="trust-bar"><i style={{ width: `${station.trust_score}%` }} /></span><strong className="trust-number">{station.trust_score}%</strong></button>)}{!filteredStations.length && <p className="empty-message">No stations match your search.</p>}</div></article>
                <article className="panel report-panel"><div className="panel-heading"><div><h2>Community report</h2><p>Cross-check a local reading</p></div><span className="report-mark"><Droplets size={16} /></span></div><form className="report-form" onSubmit={handleFeedbackSubmit}><label className="sr-only" htmlFor="field-report">Field report</label><input id="field-report" value={farmerInput} onChange={(event) => setFarmerInput(event.target.value)} placeholder="Describe the water conditions..." /><div className="report-actions"><select aria-label="Report language" value={farmerLang} onChange={(event) => setFarmerLang(event.target.value)}><option>Sepedi</option><option>isiZulu</option><option>Afrikaans</option></select><button type="submit" aria-label="Send community report"><Send size={15} /></button></div>{feedbackStatus && <p className="feedback-status"><Check size={13} />{feedbackStatus}</p>}</form></article>
              </section>
            </>
          ) : activeTab === 'reports' ? (
            <section className="panel full-panel"><div className="panel-heading"><div><span className="eyebrow">Community network</span><h2>Multilingual alerts</h2><p>Current reports from monitored catchments.</p></div><span className="report-mark"><Bell size={17} /></span></div><div className="reports-grid">{alertsData.map((alert, index) => <article className="report-card" key={`${alert.station_id}-${index}`}><div className="report-card-top"><span>{alert.language}</span><StatusPill status={alert.status} /></div><p>{alert.message}</p><div className="report-card-foot"><span>{alert.station_id}</span><strong>Trust {alert.trust_score}%</strong></div></article>)}</div><form className="report-form report-form-wide" onSubmit={handleFeedbackSubmit}><label htmlFor="field-report-wide">Submit a field report</label><textarea id="field-report-wide" value={farmerInput} onChange={(event) => setFarmerInput(event.target.value)} placeholder="Describe the water conditions..." /><div className="report-actions"><select aria-label="Report language" value={farmerLang} onChange={(event) => setFarmerLang(event.target.value)}><option>Sepedi</option><option>isiZulu</option><option>Afrikaans</option></select><button type="submit"><Send size={15} />Send report</button></div>{feedbackStatus && <p className="feedback-status"><Check size={13} />{feedbackStatus}</p>}</form></section>
          ) : activeTab === 'ledger' ? (
            <section className="panel full-panel"><div className="panel-heading"><div><span className="eyebrow">Immutable record</span><h2>Trust decision ledger</h2><p>Recorded station evaluations and alert decisions.</p></div><ShieldCheck className="ledger-heading-icon" size={24} /></div><div className="ledger-list"><article className="ledger-row"><div className="ledger-time"><span className="ledger-dot verified" /><time>2026-10-07 · 20:00 SAST</time></div><div><strong>Live ingestion validated</strong><p>DWS station feed received and trust metrics evaluated.</p></div><span className="ledger-badge verified">Hash verified</span></article><article className="ledger-row"><div className="ledger-time"><span className="ledger-dot review" /><time>2026-10-07 · 19:45 SAST</time></div><div><strong>Anomaly review recorded</strong><p>Stale data flagged and trust-gated alert withheld.</p></div><span className="ledger-badge review">Hold for review</span></article></div></section>
          ) : (
            <section className="secondary-layout">
              <article className="panel secondary-main"><div className="panel-heading"><div><span className="eyebrow">{selectedStation?.catchment || 'HydroLink network'}</span><h2>{activeTab === 'network' ? 'Catchment network' : activeTab === 'forecast' ? 'River forecast' : activeTab === 'quality' ? 'Water integrity' : activeTab === 'insights' ? 'AI trust insights' : activeTab === 'devices' ? 'Connected devices' : 'Station monitoring'}</h2><p>Live readings and confidence metrics from connected stations.</p></div><Gauge className="ledger-heading-icon" size={23} /></div>
                {activeTab === 'network' && <div className="network-visual"><div className="network-river" /><span className="map-label">Limpopo catchment</span>{dashboardData.map((station, index) => <button key={station.station_id} className={`map-node node-${index}`} onClick={() => setSelectedStationId(station.station_id)}><span /><strong>{station.station_id}</strong><small>{station.current_value} m</small></button>)}</div>}
                {activeTab === 'forecast' && <div className="forecast-focus"><span className="forecast-value">{stationReading?.forecast?.predicted_level ?? '--'}<small> m</small></span><span className="forecast-label">Predicted level · next 24 hours</span><div className="forecast-chart"><svg viewBox="0 0 600 120" preserveAspectRatio="none"><path d="M0 84 C80 79 95 65 160 72 S250 47 315 57 S420 36 480 43 S550 18 600 25" /><path className="chart-baseline" d="M0 104 H600" /></svg></div><p>Confidence interval: {stationReading?.forecast?.confidence_interval || 'pending'} · Current baseline: {stationReading?.expected_range || 'pending'}</p></div>}
                {(activeTab === 'insights' || activeTab === 'quality') && <div className="insight-copy"><div className="insight-score"><span>{stationReading?.trust_score ?? '--'}<small>/100</small></span><div><strong>{activeTab === 'quality' ? 'Measurement integrity' : 'Station trust score'}</strong><p>{stationReading?.anomalies_flagged || 'No anomaly details are currently available.'}</p></div></div><div className="insight-facts"><div><span>Observed level</span><strong>{stationReading?.current_value ?? '--'} m</strong></div><div><span>Expected range</span><strong>{stationReading?.expected_range || '--'}</strong></div><div><span>Station condition</span><StatusPill status={stationReading?.status} /></div></div></div>}
                {(activeTab === 'monitoring' || activeTab === 'devices') && <div className="station-table">{filteredStations.map((station) => <button className={`station-table-row ${station.station_id === selectedStationId ? 'selected' : ''}`} key={station.station_id} onClick={() => setSelectedStationId(station.station_id)}><span><span className={`mini-status ${station.status === 'healthy' ? '' : 'review'}`} /><span><strong>{station.name}</strong><small>{station.station_id} · {station.catchment}</small></span></span><span>{station.current_value} m</span><span>{station.trust_score}% trust</span><StatusPill status={station.status} /><ChevronRight size={15} /></button>)}</div>}
              </article>
              <aside className="panel station-picker"><div className="panel-heading"><div><h2>Stations</h2><p>Select a live node</p></div></div>{filteredStations.map((station) => <button key={station.station_id} className={`picker-row ${station.station_id === selectedStationId ? 'selected' : ''}`} onClick={() => setSelectedStationId(station.station_id)}><span className={`mini-status ${station.status === 'healthy' ? '' : 'review'}`} /><span><strong>{station.name}</strong><small>{station.station_id}</small></span><ChevronRight size={14} /></button>)}</aside>
            </section>
          )}
          <footer className="page-footer"><span><span className="status-dot" />Data sync active</span><span>HydroLink SA · Water operations</span><button onClick={() => selectTab('ledger')}><Clock3 size={12} />Last audit <ChevronRight size={12} /></button></footer>
        </div>
      </main>
      {mobileNavOpen && <button className="mobile-scrim" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
    </div>
  );
}

export function LegacyHydroLinkApp() {
  const [activeTab, setActiveTab] = useState('controlRoom');
  const [dashboardData, setDashboardData] = useState([]);
  const [selectedStationId, setSelectedStationId] = useState('');
  const [stationReading, setStationReading] = useState(null);
  const [alertsData, setAlertsData] = useState([]);
  
  // UI states for loading & error feedback
  const [isLoading, setIsLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);

  // Form state for interactive WhatsApp feedback simulation
  const [farmerInput, setFarmerInput] = useState('');
  const [farmerLang, setFarmerLang] = useState('Sepedi');
  const [feedbackLog, setFeedbackLog] = useState([]);
  const [feedbackStatus, setFeedbackStatus] = useState(null);

  const API_BASE = 'http://localhost:8000/api';

  // 1. Fetch Live Dashboard Data & Alerts on Mount
  useEffect(() => {
    async function fetchAppData() {
      setIsLoading(true);
      setErrorMsg(null);
      try {
        const dashRes = await fetch(`${API_BASE}/dashboard`);
        if (!dashRes.ok) throw new Error("Failed to fetch live DWS scraped feeds from backend.");
        const dashJson = await dashRes.json();
        
        setDashboardData(dashJson);
        if (dashJson.length > 0) {
          setSelectedStationId(dashJson[0].station_id);
        }

        const alertRes = await fetch(`${API_BASE}/alerts`);
        const alertJson = await alertRes.json();
        setAlertsData(alertJson);
      } catch (err) {
        setErrorMsg(err.message || "Connection error. Ensure FastAPI backend is running.");
      } finally {
        setIsLoading(false);
      }
    }
    fetchAppData();
  }, []);

  // 2. Fetch Selected Station Detail
  useEffect(() => {
    if (!selectedStationId) return;
    async function fetchStationDetails() {
      try {
        const res = await fetch(`${API_BASE}/readings?station_id=${selectedStationId}`);
        if (!res.ok) throw new Error("Station detail lookup failed.");
        const data = await res.json();
        setStationReading(data);
      } catch (err) {
        console.error(err);
      }
    }
    fetchStationDetails();
  }, [selectedStationId]);

  // 3. Handle Farmer Feedback Submission
  const handleFeedbackSubmit = async (e) => {
    e.preventDefault();
    if (!farmerInput.trim()) return;
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
      
      setFeedbackLog([result, ...feedbackLog]);
      setFeedbackStatus(result.message);
      setFarmerInput('');
    } catch {
      setFeedbackStatus("Failed to transmit report to backend API.");
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans selection:bg-cyan-500 selection:text-slate-950">
      
      {/* TOP HEADER NAVIGATION BAR */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur sticky top-0 z-30 px-6 py-4">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <div className="flex items-center space-x-3">
              <span className="bg-cyan-500 text-slate-950 text-[10px] font-black px-2 py-0.5 rounded tracking-widest uppercase">
                Live DWS Scraped Engine
              </span>
              <span className="text-xs text-slate-400 font-mono">HydroLink SA Trust Layer</span>
            </div>
            <h1 className="text-2xl font-black tracking-tight text-white mt-1">
              Control <span className="text-cyan-400">Center</span>
            </h1>
          </div>

          {/* TAB SWITCHER */}
          <nav className="flex space-x-1 bg-slate-950 p-1 rounded-lg border border-slate-800">
            {[
              { id: 'controlRoom', label: 'Municipal Dashboard' },
              { id: 'community', label: 'WhatsApp & Alerts' },
              { id: 'audit', label: 'IBM Z Ledger' }
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2 rounded-md text-xs font-semibold transition-all duration-150 ${
                  activeTab === tab.id
                    ? 'bg-cyan-500 text-slate-950 shadow-sm'
                    : 'text-slate-400 hover:text-white hover:bg-slate-900'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {/* MAIN CONTAINER CONTENT */}
      <main className="max-w-7xl mx-auto p-6">

        {/* ERROR STATE BANNER */}
        {errorMsg && (
          <div className="mb-6 bg-rose-950/40 border border-rose-800/80 p-4 rounded-xl flex items-center justify-between text-rose-200 text-xs">
            <span>{errorMsg}</span>
            <span className="font-mono text-[10px] bg-rose-900 px-2 py-1 rounded">Check FastAPI Backend Server</span>
          </div>
        )}

        {/* LOADING STATE */}
        {isLoading && !errorMsg && (
          <div className="flex flex-col items-center justify-center py-24 space-y-3">
            <div className="w-8 h-8 border-4 border-cyan-500 border-t-transparent rounded-full animate-spin"></div>
            <p className="text-xs text-slate-400 font-mono animate-pulse">Scraping live DWS stations & validating trust metrics...</p>
          </div>
        )}

        {/* TAB 1: CONTROL ROOM */}
        {!isLoading && activeTab === 'controlRoom' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            
            {/* LEFT COLUMN: STATION LIST (4 Cols) */}
            <div className="lg:col-span-4 bg-slate-900/60 border border-slate-800/80 rounded-2xl p-5 flex flex-col h-[700px]">
              <div className="mb-4">
                <h3 className="text-xs font-bold text-white uppercase tracking-wider">Discovered Telemetry Feeds</h3>
                <p className="text-[11px] text-slate-400 mt-0.5">Zero-hardcoded stations parsed from live tables.</p>
              </div>

              <div className="space-y-2.5 overflow-y-auto pr-1 flex-1">
                {dashboardData.length === 0 ? (
                  <p className="text-xs text-slate-500 text-center py-10">No active stations returned.</p>
                ) : (
                  dashboardData.map((st) => (
                    <div
                      key={st.station_id}
                      onClick={() => setSelectedStationId(st.station_id)}
                      className={`p-3.5 rounded-xl border transition-all duration-200 cursor-pointer ${
                        selectedStationId === st.station_id
                          ? 'bg-slate-800/90 border-cyan-500 shadow-lg shadow-cyan-950/20'
                          : 'bg-slate-950/40 border-slate-800/60 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex justify-between items-center">
                        <span className="text-xs font-mono font-bold text-cyan-300">{st.station_id}</span>
                        <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase tracking-wider ${
                          st.status === 'healthy' 
                            ? 'bg-emerald-950 text-emerald-300 border border-emerald-800/50' 
                            : 'bg-amber-950 text-amber-300 border border-amber-800/50'
                        }`}>
                          {st.status}
                        </span>
                      </div>
                      <p className="text-xs font-semibold text-slate-200 mt-2 truncate">{st.name}</p>
                      <div className="flex justify-between items-center mt-3 pt-2 border-t border-slate-800/40 text-[10px] text-slate-400 font-mono">
                        <span>Level: {st.current_value}m</span>
                        <span className="text-cyan-400">Trust: {st.trust_score}%</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* RIGHT COLUMN: DEEP-DIVE TELEMETRY & FEEDBACK (8 Cols) */}
            <div className="lg:col-span-8 space-y-6">
              {stationReading ? (
                <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-6 space-y-6">
                  
                  {/* Header info */}
                  <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center border-b border-slate-800 pb-4 gap-4">
                    <div>
                      <span className="text-xs font-mono text-cyan-400 uppercase tracking-widest">Active Node Analysis</span>
                      <h2 className="text-xl font-bold text-white mt-0.5">{stationReading.name}</h2>
                      <p className="text-xs text-slate-400 font-mono mt-1">Catchment Basin: {stationReading.catchment}</p>
                    </div>
                    <div className="flex items-center space-x-2 bg-slate-950 border border-slate-800 px-3 py-1.5 rounded-xl">
                      <span className="text-xs text-slate-400">AI Trust Score:</span>
                      <span className={`text-sm font-black ${stationReading.trust_score >= 80 ? 'text-emerald-400' : 'text-amber-400'}`}>
                        {stationReading.trust_score} / 100
                      </span>
                    </div>
                  </div>

                  {/* Metrics Grid */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="bg-slate-950/60 p-4 rounded-xl border border-slate-800/60">
                      <span className="text-xs text-slate-400 font-medium">Live Stage Height</span>
                      <p className="text-2xl font-black text-white mt-1">{stationReading.current_value} <span className="text-sm font-normal text-slate-400">meters</span></p>
                      <span className="text-[10px] text-cyan-400/80 font-mono mt-1 block">Expected Baseline: {stationReading.expected_range}</span>
                    </div>

                    <div className="bg-slate-950/60 p-4 rounded-xl border border-slate-800/60">
                      <span className="text-xs text-slate-400 font-medium">24-Hour Predictive Forecast</span>
                      <p className="text-2xl font-black text-cyan-400 mt-1">{stationReading.forecast.predicted_level} <span className="text-sm font-normal text-slate-400">m</span></p>
                      <span className="text-[10px] text-slate-400 font-mono mt-1 block">Confidence Interval: {stationReading.forecast.confidence_interval}</span>
                    </div>
                  </div>

                  {/* Explainability Audit Box */}
                  <div className="bg-slate-950 p-4 rounded-xl border border-slate-800/80 space-y-1.5">
                    <h4 className="text-[11px] font-bold text-slate-300 uppercase tracking-wider flex items-center space-x-2">
                      <span>AI Trust Layer Audit Log</span>
                    </h4>
                    <p className="text-xs text-slate-400 font-mono leading-relaxed italic">
                      "{stationReading.anomalies_flagged}"
                    </p>
                  </div>

                  {/* Simulated Farmer WhatsApp Feedback */}
                  <div className="border-t border-slate-800 pt-6">
                    <h3 className="text-xs font-bold text-white uppercase tracking-wider mb-1">Decentralized Community Cross-Check</h3>
                    <p className="text-xs text-slate-400 mb-4">Simulate a smallholder farmer text update to test real-time trust recalibration.</p>
                    
                    <form onSubmit={handleFeedbackSubmit} className="space-y-3">
                      <div className="grid grid-cols-1 sm:grid-cols-12 gap-3">
                        <input
                          type="text"
                          placeholder="e.g., Water level is approaching bridge deck..."
                          value={farmerInput}
                          onChange={(e) => setFarmerInput(e.target.value)}
                          className="sm:col-span-8 bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500"
                        />
                        <select
                          value={farmerLang}
                          onChange={(e) => setFarmerLang(e.target.value)}
                          className="sm:col-span-4 bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-xs text-white focus:outline-none focus:border-cyan-500"
                        >
                          <option value="Sepedi">Sepedi</option>
                          <option value="isiZulu">isiZulu</option>
                          <option value="Afrikaans">Afrikaans</option>
                        </select>
                      </div>
                      <button
                        type="submit"
                        className="w-full sm:w-auto px-5 py-2.5 bg-cyan-500 text-slate-950 rounded-xl text-xs font-bold hover:bg-cyan-400 transition-colors shadow-sm"
                      >
                        Transmit WhatsApp Report
                      </button>
                      {feedbackStatus && (
                        <p className="text-xs text-cyan-300 font-mono mt-2 bg-cyan-950/30 border border-cyan-800/40 p-2.5 rounded-lg">
                          {feedbackStatus}
                        </p>
                      )}
                    </form>

                    {/* Feedback Activity Feed */}
                    {feedbackLog.length > 0 && (
                      <div className="mt-4 space-y-2">
                        <h4 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Recent Session Submissions:</h4>
                        {feedbackLog.map((log, idx) => (
                          <div key={idx} className="bg-slate-950/80 border border-slate-800 p-3 rounded-xl text-xs flex justify-between items-center">
                            <div>
                              <span className="text-slate-200 font-medium italic">"{log.report}"</span>
                              <span className="text-[10px] text-slate-500 ml-2 font-mono">({log.lang})</span>
                            </div>
                            <span className="text-cyan-400 font-mono text-[10px] bg-cyan-950 px-2 py-0.5 rounded border border-cyan-800/50">
                              {log.impact}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                </div>
              ) : (
                <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-12 text-center text-slate-500 text-xs">
                  Select a station from the left column to inspect telemetry.
                </div>
              )}
            </div>

          </div>
        )}

        {/* TAB 2: WHATSAPP ALERTS */}
        {!isLoading && activeTab === 'community' && (
          <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-6 space-y-6">
            <div>
              <h3 className="text-lg font-bold text-white">Multilingual Community Alerts</h3>
              <p className="text-xs text-slate-400 mt-0.5">Plain-language warning broadcasts generated dynamically from live catchment telemetry.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {alertsData.map((al, idx) => (
                <div key={idx} className="bg-slate-950 border border-slate-800/80 p-5 rounded-2xl space-y-4 relative overflow-hidden flex flex-col justify-between">
                  <div className="absolute top-0 left-0 w-1.5 h-full bg-cyan-500"></div>
                  <div className="space-y-3">
                    <div className="flex justify-between items-center">
                      <span className="text-[10px] font-mono bg-slate-900 text-cyan-400 px-2 py-0.5 rounded uppercase border border-slate-800">
                        {al.language}
                      </span>
                      <span className="text-[10px] font-mono text-slate-500">{al.station_id}</span>
                    </div>
                    <p className="text-xs text-slate-200 font-medium italic leading-relaxed">
                      "{al.message}"
                    </p>
                  </div>
                  <div className="pt-3 border-t border-slate-900 flex justify-between items-center text-[11px]">
                    <span className="text-slate-400 font-mono">Trust: {al.trust_score}%</span>
                    <span className="text-cyan-400 font-bold">{al.status}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 3: IBM Z AUDIT LEDGER */}
        {!isLoading && activeTab === 'audit' && (
          <div className="bg-slate-900/60 border border-slate-800/80 rounded-2xl p-6 space-y-4">
            <div className="border-b border-slate-800 pb-4">
              <h3 className="text-lg font-bold text-white">Cryptographic Transaction & Decision Log</h3>
              <p className="text-xs text-slate-400 mt-0.5">Simulated immutable IBM Z ledger recording all automated trust evaluations and gated alerts.</p>
            </div>
            
            <div className="space-y-3 font-mono text-xs">
              <div className="bg-slate-950 p-4 rounded-xl border border-slate-800/80 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                <div>
                  <span className="text-cyan-400">[TIMESTAMP: 2026-10-07 20:00:00 SAST]</span>
                  <p className="text-slate-300 mt-1">EVENT: Live Ingestion &bull; DWS Unverified Scraped Nodes &bull; Z-Score Normalization Passed</p>
                </div>
                <span className="text-[10px] bg-cyan-950 text-cyan-300 px-2.5 py-1 rounded-lg border border-cyan-800/60 font-bold">
                  HASH_VERIFIED
                </span>
              </div>
              
              <div className="bg-slate-950 p-4 rounded-xl border border-slate-800/80 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                <div>
                  <span className="text-amber-400">[TIMESTAMP: 2026-10-07 19:45:12 SAST]</span>
                  <p className="text-slate-300 mt-1">EVENT: Anomaly Check &bull; Stale Data Flagged &bull; Trust-Gated Alert Withheld</p>
                </div>
                <span className="text-[10px] bg-amber-950 text-amber-300 px-2.5 py-1 rounded-lg border border-amber-800/60 font-bold">
                  HOLD_FOR_REVIEW
                </span>
              </div>
            </div>
          </div>
        )}

      </main>
    </div>
  );
}