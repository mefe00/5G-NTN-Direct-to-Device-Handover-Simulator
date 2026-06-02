import { useEffect, useRef, useState, useCallback } from 'react'
import {
  LineChart, Line, AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Brush, ReferenceLine, Legend,
} from 'recharts'

const MAX_POINTS = 150
// Backend adresi: aynı origin'den servis edilirse otomatik; dev modunda localhost:8000
const DEV_BACKEND = 'http://localhost:8000'
const IS_DEV = import.meta.env.DEV
const HTTP_ORIGIN = IS_DEV ? DEV_BACKEND : window.location.origin
const WS_ORIGIN = HTTP_ORIGIN.replace(/^http/, 'ws')
const BACKEND_HTTP = HTTP_ORIGIN
const BACKEND_WS = `${WS_ORIGIN}/ws/simulation`

const STATE_META = {
  TERRESTRIAL:   { label: 'KARASAL AĞ AKTİF',     color: '#34f5a8', glow: 'text-glow-green', ring: 'border-emerald-500/40' },
  DISASTER:      { label: 'AĞ ÇÖKTÜ',             color: '#ff4d6d', glow: 'text-glow-red',   ring: 'border-red-500/60' },
  SCANNING:      { label: 'UYDU TARANIYOR',       color: '#fbbf24', glow: 'text-glow-amber', ring: 'border-amber-500/50' },
  HANDOVER:      { label: 'UYDULAR ARASI GEÇİŞ',  color: '#fbbf24', glow: 'text-glow-amber', ring: 'border-amber-500/60' },
  NTN_CONNECTED: { label: 'NTN UYDU LİNKİ AKTİF', color: '#22d3ee', glow: 'text-glow-cyan',  ring: 'border-cyan-500/50' },
}
const LOG_COLOR = { info: '#7dd3fc', warn: '#fbbf24', error: '#ff4d6d', success: '#34f5a8' }

const fmtTime = (s) => new Date(s * 1000).toLocaleTimeString('tr-TR', { hour12: false })

// ---------------------------------------------------------------------------
// Modal sarmalayıcı: arka plan blur + ortada büyük görünüm
// ---------------------------------------------------------------------------
function Modal({ title, onClose, children }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-box panel panel-glow-cyan rounded-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#16243f] shrink-0">
          <h2 className="font-display text-base font-bold tracking-wide text-cyan-300 text-glow-cyan">{title}</h2>
          <div className="modal-close" onClick={onClose} title="Kapat (Esc)">✕</div>
        </div>
        <div className="flex-1 min-h-0 p-5">{children}</div>
      </div>
    </div>
  )
}

// Tıklanabilir panel sarmalayıcı
function Panel({ title, onExpand, children, className = '', noPad = false }) {
  return (
    <div className={`panel rounded-lg flex flex-col min-h-0 clickable ${className}`}
         onClick={onExpand}>
      {title && (
        <div className="flex items-center justify-between px-3 pt-2 pb-1 shrink-0">
          <h3 className="text-[10px] font-bold tracking-[0.2em] uppercase text-slate-400">{title}</h3>
          <span className="expand-hint text-[9px] text-cyan-400">⤢ büyüt</span>
        </div>
      )}
      <div className={`flex-1 min-h-0 ${noPad ? '' : 'px-3 pb-3'} ${title ? '' : 'pt-3'}`}>
        {children}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Grafik — net, kalın çizgi; expanded modunda eksenler/legend daha detaylı
// ---------------------------------------------------------------------------
function CustomTooltip({ active, payload, label, unit, color }) {
  if (!active || !payload?.length) return null
  return (
    <div className="panel px-3 py-2 text-xs rounded" style={{ borderColor: color }}>
      <div className="text-slate-400 mb-1">t = {Number(label).toFixed(2)} s</div>
      <div className="font-bold text-base" style={{ color }}>
        {Number(payload[0].value).toFixed(3)} <span className="text-slate-400 text-xs">{unit}</span>
      </div>
    </div>
  )
}

function MetricChart({ data, dataKey, color, unit, title, domain, threshold, expanded = false }) {
  const last = data.length ? data[data.length - 1][dataKey] : null
  const gradId = `grad-${dataKey}${expanded ? '-x' : ''}`
  return (
    <div className="flex flex-col min-h-0 h-full">
      {!expanded && (
        <div className="flex justify-between items-baseline mb-1 px-3 pt-2">
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-4 rounded-sm" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
            <h3 className="text-xs font-bold tracking-[0.2em] uppercase text-slate-300">{title}</h3>
            <span className="expand-hint text-[9px] text-cyan-400">⤢</span>
          </div>
          <div className="text-right">
            <span className="text-2xl font-bold tabular-nums" style={{ color, textShadow: `0 0 12px ${color}88` }}>
              {last != null ? last.toFixed(1) : '—'}
            </span>
            <span className="text-slate-500 text-xs ml-1">{unit}</span>
          </div>
        </div>
      )}
      {expanded && (
        <div className="flex items-baseline gap-3 mb-3">
          <span className="text-4xl font-bold tabular-nums" style={{ color, textShadow: `0 0 16px ${color}` }}>
            {last != null ? last.toFixed(2) : '—'}
          </span>
          <span className="text-slate-400 text-lg">{unit}</span>
          <span className="text-slate-500 text-xs ml-auto">son {data.length} örnek · 10 Hz</span>
        </div>
      )}
      <div className="flex-1 min-h-0 px-2 pb-2">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 6, right: 12, left: expanded ? 4 : -16, bottom: expanded ? 4 : 0 }}>
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.4} />
                <stop offset="100%" stopColor={color} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#1c2e4f" strokeDasharray={expanded ? '3 3' : '2 5'} vertical={expanded} />
            <XAxis dataKey="t" tick={{ fontSize: expanded ? 12 : 9, fill: '#6b7d9a' }}
                   tickFormatter={(v) => v.toFixed(0) + 's'} stroke="#1c2e4f"
                   interval="preserveStartEnd" minTickGap={expanded ? 40 : 60} />
            <YAxis tick={{ fontSize: expanded ? 12 : 9, fill: '#6b7d9a' }} domain={domain} stroke="#1c2e4f"
                   width={expanded ? 50 : 40} label={expanded ? { value: unit, angle: -90, position: 'insideLeft', fill: '#6b7d9a', fontSize: 12 } : undefined} />
            <Tooltip content={<CustomTooltip unit={unit} color={color} />} />
            {threshold != null && (
              <ReferenceLine y={threshold} stroke="#ff4d6d" strokeDasharray="4 3" strokeOpacity={0.6}
                             label={expanded ? { value: `eşik ${threshold}`, fill: '#ff4d6d', fontSize: 11, position: 'right' } : undefined} />
            )}
            <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={expanded ? 2.5 : 2}
                  fill={`url(#${gradId})`} dot={false} isAnimationActive={false}
                  activeDot={{ r: 5, fill: color, stroke: '#050810', strokeWidth: 2 }} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function CombinedChart({ data, expanded = false }) {
  return (
    <div className="flex flex-col min-h-0 h-full">
      {!expanded && (
        <div className="flex items-center gap-2 mb-1 px-3 pt-2">
          <div className="w-1.5 h-4 rounded-sm bg-cyan-400" style={{ boxShadow: '0 0 8px #22d3ee' }} />
          <h3 className="text-xs font-bold tracking-[0.2em] uppercase text-slate-300">Birleşik Telemetri</h3>
          <span className="text-slate-500 text-[10px]">(sürükle = zoom)</span>
          <span className="expand-hint text-[9px] text-cyan-400 ml-auto">⤢ büyüt</span>
        </div>
      )}
      <div className="flex-1 min-h-0 px-2 pb-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 6, right: 12, left: expanded ? 4 : -16, bottom: 0 }}>
            <CartesianGrid stroke="#1c2e4f" strokeDasharray="2 5" />
            <XAxis dataKey="t" tick={{ fontSize: expanded ? 12 : 9, fill: '#6b7d9a' }}
                   tickFormatter={(v) => v.toFixed(0) + 's'} stroke="#1c2e4f"
                   interval="preserveStartEnd" minTickGap={50} />
            <YAxis tick={{ fontSize: expanded ? 12 : 9, fill: '#6b7d9a' }} stroke="#1c2e4f" width={expanded ? 50 : 40} />
            <Tooltip contentStyle={{ background: '#0a1020', border: '1px solid #22d3ee', fontSize: 11, borderRadius: 6 }}
                     labelFormatter={(v) => `t = ${Number(v).toFixed(2)} s`}
                     formatter={(v, n) => [Number(v).toFixed(2), n]} />
            {expanded && <Legend wrapperStyle={{ fontSize: 12 }} />}
            <Line type="monotone" dataKey="throughput" name="Throughput (Mbps)" stroke="#22d3ee" strokeWidth={1.8} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="latency" name="Latency (ms)" stroke="#fbbf24" strokeWidth={1.8} dot={false} isAnimationActive={false} />
            <Line type="monotone" dataKey="snr" name="SNR (dB)" stroke="#34f5a8" strokeWidth={1.8} dot={false} isAnimationActive={false} />
            <Brush dataKey="t" height={expanded ? 28 : 20} stroke="#22d3ee" fill="#0a1020"
                   tickFormatter={(v) => Number(v).toFixed(0)} travellerWidth={8} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Skyplot
// ---------------------------------------------------------------------------
function Skyplot({ visible, selectedSatnum, expanded = false }) {
  const size = 240
  const cx = size / 2, cy = size / 2, R = size / 2 - 16
  const project = (az, elev) => {
    const r = R * (1 - Math.max(0, Math.min(90, elev)) / 90)
    const rad = (az - 90) * Math.PI / 180
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)]
  }
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-full h-full" style={{ maxHeight: expanded ? '70vh' : 'none' }}>
      {[1, 2 / 3, 1 / 3].map((f, i) => (
        <circle key={i} cx={cx} cy={cy} r={R * f} fill="none" stroke="#1c2e4f" strokeWidth="1" />
      ))}
      {expanded && [30, 60].map((e, i) => (
        <text key={i} x={cx + 4} y={cy - R * (1 - e / 90) - 2} fill="#5b6b85" fontSize="8">{e}°</text>
      ))}
      <circle cx={cx} cy={cy} r="2.5" fill="#22d3ee" />
      <line x1={cx} y1={cy - R} x2={cx} y2={cy + R} stroke="#1c2e4f" strokeWidth="1" />
      <line x1={cx - R} y1={cy} x2={cx + R} y2={cy} stroke="#1c2e4f" strokeWidth="1" />
      <text x={cx} y={cy - R - 4} fill="#6b7d9a" fontSize="9" textAnchor="middle">K</text>
      <text x={cx} y={cy + R + 10} fill="#6b7d9a" fontSize="9" textAnchor="middle">G</text>
      <text x={cx + R + 7} y={cy + 3} fill="#6b7d9a" fontSize="9" textAnchor="middle">D</text>
      <text x={cx - R - 7} y={cy + 3} fill="#6b7d9a" fontSize="9" textAnchor="middle">B</text>
      <g className="radar-sweep" style={{ transformOrigin: `${cx}px ${cy}px` }}>
        <line x1={cx} y1={cy} x2={cx} y2={cy - R} stroke="#22d3ee" strokeWidth="1.5" strokeOpacity="0.5" />
        <path d={`M ${cx} ${cy} L ${cx} ${cy - R} A ${R} ${R} 0 0 1 ${cx + R * 0.5} ${cy - R * 0.87} Z`}
              fill="#22d3ee" fillOpacity="0.08" />
      </g>
      {visible.map((s) => {
        const [x, y] = project(s.azimuth, s.elevation)
        const isSel = s.satnum === selectedSatnum
        return (
          <g key={s.satnum}>
            <circle cx={x} cy={y} r={isSel ? 5.5 : 3.5}
                    fill={isSel ? '#22d3ee' : '#34f5a8'} fillOpacity={isSel ? 1 : 0.75}
                    style={isSel ? { filter: 'drop-shadow(0 0 6px #22d3ee)' } : {}} />
            {isSel && <circle cx={x} cy={y} r="10" fill="none" stroke="#22d3ee" strokeWidth="1" strokeOpacity="0.6" />}
            {expanded && (
              <text x={x + 7} y={y + 3} fill={isSel ? '#22d3ee' : '#7d9bc0'} fontSize="8">
                {s.name?.replace('STARLINK-', 'SL-')}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Görünür uydu tablosu
// ---------------------------------------------------------------------------
function VisibleSatTable({ visible, selectedSatnum, expanded = false }) {
  const fs = expanded ? 'text-sm' : 'text-[10px]'
  return (
    <div className={`list-scroll overflow-y-auto h-full ${fs}`}>
      <table className="w-full">
        <thead className="sticky top-0 bg-[#0a1020] text-slate-500 uppercase tracking-wider">
          <tr className="border-b border-[#1c2e4f]">
            <th className="text-left py-1.5 px-1.5 font-medium">Uydu</th>
            <th className="text-right py-1.5 px-1.5 font-medium">Az°</th>
            <th className="text-right py-1.5 px-1.5 font-medium">El°</th>
            <th className="text-right py-1.5 px-1.5 font-medium">km</th>
            <th className="text-right py-1.5 px-1.5 font-medium">FSPL</th>
            {expanded && <th className="text-right py-1.5 px-1.5 font-medium">SNR</th>}
            {expanded && <th className="text-right py-1.5 px-1.5 font-medium">MODCOD</th>}
            {expanded && <th className="text-right py-1.5 px-1.5 font-medium">NORAD</th>}
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {visible.length === 0 && (
            <tr><td colSpan={expanded ? 8 : 5} className="text-slate-600 italic py-3 text-center">
              Görünür uydu yok (afet tetiklenince dolar)
            </td></tr>
          )}
          {visible.map((s) => {
            const isSel = s.satnum === selectedSatnum
            return (
              <tr key={s.satnum} className={`border-b border-[#0d1528] ${isSel ? 'bg-cyan-500/10' : ''}`}>
                <td className={`py-1 px-1.5 truncate ${expanded ? 'max-w-none' : 'max-w-[90px]'} ${isSel ? 'text-cyan-300 font-bold' : 'text-slate-300'}`}>
                  {isSel && '▸ '}{s.name}
                </td>
                <td className="text-right py-1 px-1.5 text-slate-400">{s.azimuth.toFixed(0)}</td>
                <td className="text-right py-1 px-1.5" style={{ color: s.elevation > 40 ? '#34f5a8' : '#fbbf24' }}>{s.elevation.toFixed(1)}</td>
                <td className="text-right py-1 px-1.5 text-slate-400">{s.distance_km.toFixed(0)}</td>
                <td className="text-right py-1 px-1.5 text-slate-500">{s.fspl_db.toFixed(1)}</td>
                {expanded && <td className="text-right py-1 px-1.5" style={{ color: s.snr_db > 6 ? '#34f5a8' : '#fbbf24' }}>{s.snr_db != null ? s.snr_db.toFixed(1) : '—'}</td>}
                {expanded && <td className="text-right py-1 px-1.5 text-cyan-300">{s.modcod || '—'}</td>}
                {expanded && <td className="text-right py-1 px-1.5 text-slate-500">#{s.satnum}</td>}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Log terminali
// ---------------------------------------------------------------------------
function LogTerminal({ logs, expanded = false }) {
  const ref = useRef(null)
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight }, [logs])
  return (
    <div ref={ref} className={`log-scroll h-full overflow-y-auto px-3 py-2 leading-relaxed ${expanded ? 'text-sm' : 'text-[11px]'}`}>
      {logs.length === 0 && <div className="text-slate-600 italic">// sistem hazır — karar logları burada akacak...</div>}
      {logs.map((l, i) => (
        <div key={i} className="log-line flex gap-2">
          <span className="text-slate-600 shrink-0">[{fmtTime(l.time)}]</span>
          <span style={{ color: LOG_COLOR[l.level] || '#cbd5e1' }}>{l.msg}</span>
        </div>
      ))}
    </div>
  )
}

function Metric({ label, value, color = '#cbd5e1', span = false, big = false }) {
  return (
    <div className={`bg-black/30 rounded px-2 py-1.5 ${span ? 'col-span-2' : ''}`}>
      <div className={`${big ? 'text-[11px]' : 'text-[9px]'} text-slate-500 uppercase tracking-wide`}>{label}</div>
      <div className={`font-bold tabular-nums truncate ${big ? 'text-lg' : ''}`} style={{ color }}>{value}</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Handover zaman çizelgesi (dinamik geçişlerin kanıtı)
// ---------------------------------------------------------------------------
function HandoverTimeline({ events, expanded = false }) {
  if (!events?.length) {
    return <div className="text-slate-600 italic text-[11px] px-1 py-2">// henüz geçiş yok — afet tetiklenince dolar</div>
  }
  return (
    <div className={`list-scroll overflow-y-auto h-full ${expanded ? 'text-sm' : 'text-[10px]'}`}>
      <div className="flex flex-col gap-1.5 px-1">
        {events.map((e) => (
          <div key={e.index} className="flex items-start gap-2 border-l-2 pl-2 py-0.5"
               style={{ borderColor: e.index === 0 ? '#34f5a8' : '#fbbf24' }}>
            <span className="text-slate-600 shrink-0 tabular-nums">T+{e.t_rel}s</span>
            <div className="flex-1 min-w-0">
              <div className="text-slate-300 truncate">
                <span className="text-slate-500">{e.from_sat}</span>
                <span className="text-cyan-400"> → </span>
                <span className="text-cyan-300 font-bold">{e.to_sat}</span>
              </div>
              <div className="text-slate-500">
                {e.from_elev != null && <span>{e.from_elev}° → </span>}
                <span style={{ color: e.to_elev > 40 ? '#34f5a8' : '#fbbf24' }}>{e.to_elev}°</span>
                {' · '}<span className="text-slate-600">{e.reason}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Link budget breakdown (hesap şeffaflığı) — modal içinde
// ---------------------------------------------------------------------------
function LinkBudgetBreakdown({ data }) {
  if (!data || !data.ok) {
    return <div className="text-slate-500 italic">Bağlı uydu yok. Önce afeti tetikleyin.</div>
  }
  return (
    <div className="flex flex-col gap-4 text-sm">
      <div className="text-slate-400">
        Uydu: <span className="text-cyan-300 font-bold">{data.satellite}</span> ·
        Mesafe: <span className="text-slate-200">{data.distance_km} km</span> ·
        Frekans: <span className="text-slate-200">{data.freq_ghz} GHz</span>
      </div>
      <div className="font-mono">
        {data.steps.map((s, i) => (
          <div key={i} className="flex items-center gap-2 py-1 border-b border-[#0d1528]">
            <span className="w-6 text-center font-bold" style={{ color: s.op === '+' ? '#34f5a8' : '#ff4d6d' }}>{s.op}</span>
            <span className="w-24 text-right tabular-nums font-bold text-slate-200">{s.value} <span className="text-slate-500 text-xs">{s.unit}</span></span>
            <span className="flex-1 text-slate-400 text-xs">
              {s.label}
              {s.detail && <span className="text-slate-600 block">= {s.detail}</span>}
            </span>
          </div>
        ))}
      </div>
      <div className="bg-black/30 rounded p-3 grid grid-cols-2 gap-3">
        <Metric label="C/N₀" value={`${data.cn0_dbhz} dBHz`} color="#7dd3fc" big />
        <Metric label={`− 10log₁₀(BW)`} value={`−${data.bw_term_db} dB`} big />
        <Metric label="SNR Sonuç" value={`${data.snr_db} dB`} color="#22d3ee" big />
        <Metric label="Seçilen MODCOD" value={data.modcod} color="#34f5a8" big />
        <Metric label="Spektral Verim" value={`${data.spectral_eff} bps/Hz`} big />
        <Metric label="Shannon Tavanı" value={`${data.shannon_mbps} Mbps`} color="#5b6b85" big />
      </div>
      <div className="text-[11px] text-slate-600">
        Tüm değerler skyfield yörünge propagasyonundan ve standart link budget denkleminden hesaplanır.
      </div>
    </div>
  )
}

function StatusContent({ state, statusText, sat, big = false }) {
  if (sat) {
    return (
      <div className="flex flex-col gap-2">
        <div className={`grid grid-cols-2 ${big ? 'gap-3' : 'gap-1.5'} ${big ? 'text-sm' : 'text-[11px]'}`}>
          <Metric label="Uydu" value={sat.name} span color="#22d3ee" big={big} />
          <Metric label="NORAD ID" value={`#${sat.satnum}`} big={big} />
          <Metric label="MODCOD" value={sat.modcod || '—'} color="#34f5a8" big={big} />
          <Metric label="Elevasyon" value={`${sat.elevation}°`} color={sat.elevation > 40 ? '#34f5a8' : '#fbbf24'} big={big} />
          <Metric label="Azimut" value={`${sat.azimuth}°`} big={big} />
          <Metric label="Mesafe" value={`${sat.distance_km} km`} big={big} />
          <Metric label="Doppler" value={`${sat.doppler_hz > 0 ? '+' : ''}${sat.doppler_hz} Hz`} color="#fbbf24" big={big} />
          <Metric label="FSPL" value={`${sat.fspl_db} dB`} color="#ff4d6d" big={big} />
          <Metric label="SNR (anlık)" value={`${sat.snr_now_db ?? '—'} dB`} color="#22d3ee" big={big} />
        </div>

        {/* Büyütülmüş modda tam link budget zinciri */}
        {big && (
          <div className="mt-2">
            <div className="text-[11px] text-slate-500 uppercase tracking-widest mb-2">Link Budget Zinciri</div>
            <div className="grid grid-cols-3 gap-3 text-sm">
              <Metric label="Atm. Kayıp" value={`${sat.atm_loss_db ?? '—'} dB`} big />
              <Metric label="C/N₀" value={`${sat.cn0_dbhz ?? '—'} dBHz`} color="#7dd3fc" big />
              <Metric label="Spektral Verim" value={`${sat.spectral_eff ?? '—'} bps/Hz`} big />
              <Metric label="Shannon Tavanı" value={`${sat.shannon_mbps ?? '—'} Mbps`} color="#5b6b85" big />
              <Metric label="Beam Kapasitesi" value={`${sat.beam_mbps ?? '—'} Mbps`} big />
              <Metric label="Kullanıcı Hızı" value={`${sat.user_mbps ?? '—'} Mbps`} color="#34f5a8" big />
              <Metric label="Range-rate" value={`${sat.range_rate_kms} km/s`} span big />
            </div>
          </div>
        )}
      </div>
    )
  }
  if (state === 'TERRESTRIAL') {
    return (
      <div className={`grid grid-cols-2 ${big ? 'gap-3 text-sm' : 'gap-1.5 text-[11px]'}`}>
        <Metric label="Teknoloji" value="5G NR (n78)" big={big} />
        <Metric label="Frekans" value="3.5 GHz" big={big} />
        <Metric label="Hücre" value="gNodeB-IST-042" span big={big} />
      </div>
    )
  }
  return <div className="text-xs text-slate-500 italic py-2">Uydu verisi bekleniyor...</div>
}

// ---------------------------------------------------------------------------
// Ana uygulama
// ---------------------------------------------------------------------------
export default function App() {
  const [series, setSeries] = useState([])
  const [state, setState] = useState('TERRESTRIAL')
  const [statusText, setStatusText] = useState('Karasal Ağ (gNodeB 3.5 GHz)')
  const [sat, setSat] = useState(null)
  const [logs, setLogs] = useState([])
  const [visible, setVisible] = useState([])
  const [timeline, setTimeline] = useState([])
  const [meta, setMeta] = useState({ tle_source: '—', tle_epoch: '—', satellite_count: 0, observer: null })
  const [handoverCount, setHandoverCount] = useState(0)
  const [wsConnected, setWsConnected] = useState(false)
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState(null)        // hangi panel açık
  const [geoStatus, setGeoStatus] = useState('İstanbul (varsayılan)')

  // --- WebSocket ---
  useEffect(() => {
    let ws, reconnectTimer, mounted = true
    const connect = () => {
      ws = new WebSocket(BACKEND_WS)
      ws.onopen = () => mounted && setWsConnected(true)
      ws.onclose = () => { if (mounted) { setWsConnected(false); reconnectTimer = setTimeout(connect, 1500) } }
      ws.onerror = () => ws.close()
      ws.onmessage = (ev) => {
        try {
          const d = JSON.parse(ev.data)
          if (d.type === 'meta') { setMeta((m) => ({ ...m, ...d })); return }
          setState(d.state); setStatusText(d.status_text); setSat(d.satellite_info)
          setHandoverCount(d.handover_count || 0)
          if (d.observer) setMeta((m) => ({ ...m, observer: d.observer }))
          setSeries((prev) => {
            const next = [...prev, { t: d.timestamp, throughput: d.throughput, latency: d.latency, snr: d.snr }]
            return next.length > MAX_POINTS ? next.slice(-MAX_POINTS) : next
          })
          if (d.new_logs?.length) setLogs((p) => [...p, ...d.new_logs])
          if (d.visible_satellites) setVisible(d.visible_satellites)
          if (d.handover_timeline) setTimeline(d.handover_timeline)
        } catch (e) { console.error('WS', e) }
      }
    }
    connect()
    return () => { mounted = false; clearTimeout(reconnectTimer); ws && ws.close() }
  }, [])

  // --- Geolocation: açılışta + sürekli izle ---
  useEffect(() => {
    if (!('geolocation' in navigator)) {
      setGeoStatus('Tarayıcı konum desteklemiyor')
      return
    }
    const sendLoc = async (pos) => {
      const { latitude, longitude, altitude } = pos.coords
      try {
        await fetch(`${BACKEND_HTTP}/api/set_location`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            lat: latitude, lon: longitude,
            elev: altitude || 40,
          }),  // name göndermiyoruz; backend reverse-geocoding ile şehir adını çözer
        })
        setGeoStatus(`GPS kilitli: ${latitude.toFixed(4)}°, ${longitude.toFixed(4)}°`)
      } catch (e) { console.error('set_location', e) }
    }
    const onErr = (err) => {
      setGeoStatus(err.code === 1 ? 'Konum izni reddedildi (İstanbul varsayılan)' : 'Konum alınamadı (varsayılan)')
    }
    // İlk anlık konum
    navigator.geolocation.getCurrentPosition(sendLoc, onErr, { enableHighAccuracy: true, timeout: 10000 })
    // Konum değişimini sürekli izle
    const watchId = navigator.geolocation.watchPosition(sendLoc, onErr, {
      enableHighAccuracy: true, maximumAge: 5000, timeout: 15000,
    })
    return () => navigator.geolocation.clearWatch(watchId)
  }, [])

  const triggerDisaster = useCallback(async () => {
    if (busy || state !== 'TERRESTRIAL') return
    setBusy(true)
    try { await fetch(`${BACKEND_HTTP}/api/trigger_disaster`, { method: 'POST' }) }
    catch (e) { console.error(e) } finally { setTimeout(() => setBusy(false), 1000) }
  }, [busy, state])

  const resetSim = useCallback(async () => {
    try {
      await fetch(`${BACKEND_HTTP}/api/reset`, { method: 'POST' })
      setLogs([]); setSat(null); setVisible([]); setSeries([]); setTimeline([])
    } catch (e) { console.error(e) }
  }, [])

  // Link budget breakdown'ı modal açılınca getir
  const [lbData, setLbData] = useState(null)
  useEffect(() => {
    if (modal !== 'linkbudget') return
    let alive = true
    const fetchLb = async () => {
      try {
        const r = await fetch(`${BACKEND_HTTP}/api/link_budget_breakdown`)
        const d = await r.json()
        if (alive) setLbData(d)
      } catch (e) { console.error(e) }
    }
    fetchLb()
    const id = setInterval(fetchLb, 1000)  // canlı güncelle
    return () => { alive = false; clearInterval(id) }
  }, [modal])

  const downloadFile = useCallback((path) => {
    // Tarayıcıda indirme tetikle
    window.open(`${BACKEND_HTTP}${path}`, '_blank')
  }, [])

  const stopProp = (fn) => (e) => { e.stopPropagation(); fn() }
  const meta_ = STATE_META[state] || STATE_META.TERRESTRIAL
  const isTerrestrial = state === 'TERRESTRIAL'
  const selectedSatnum = sat?.satnum
  const obsLabel = meta.observer?.name || 'konum aranıyor...'
  // TLE kalite rengi
  const tleQualityColor = { 'GÜNCEL': '#34f5a8', 'KABUL EDİLEBİLİR': '#fbbf24', 'ESKİ': '#ff4d6d' }[meta.tle_quality] || '#5b6b85'

  return (
    <div className="min-h-screen w-full mission-bg flex flex-col p-3 gap-3 overflow-x-hidden">
      {/* HEADER */}
      <header className="panel rounded-lg px-4 py-2.5 flex items-center justify-between shrink-0">
        <div>
          <h1 className="font-display text-lg font-black tracking-wide text-cyan-300 text-glow-cyan">5G-NTN MISSION CONTROL</h1>
          <p className="text-[10px] text-slate-500 tracking-wide">
            DIRECT-TO-DEVICE HANDOVER · <span className="text-cyan-400">📍 {obsLabel}</span> · LEO STARLINK
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="hidden md:flex flex-col items-end text-[10px] leading-tight">
            <div className="text-slate-500">TLE: <span className="text-emerald-400">{meta.tle_source}</span></div>
            <div className="text-slate-500">
              EPOCH: <span className="text-cyan-300">{meta.tle_epoch}</span> · <span className="text-slate-400">{meta.satellite_count} uydu</span>
            </div>
            <div className="text-slate-500">
              YAŞ: <span style={{ color: tleQualityColor, fontWeight: 700 }}>
                {meta.tle_age_days != null ? `${meta.tle_age_days.toFixed(1)} gün · ${meta.tle_quality}` : '—'}
              </span>
            </div>
            <div className="text-slate-600">{geoStatus}</div>
          </div>
          <div className="flex items-center gap-2 px-2.5 py-1 rounded border border-[#16243f]">
            <span className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-emerald-400 blink' : 'bg-red-500'}`} />
            <span className="text-[10px] text-slate-400">{wsConnected ? 'CANLI 10Hz' : 'BAĞLANTI YOK'}</span>
          </div>
          <button onClick={resetSim} className="text-[10px] px-3 py-1.5 rounded border border-[#16243f] text-slate-400 hover:text-cyan-300 hover:border-cyan-500/50 transition">SIFIRLA</button>
        </div>
      </header>

      {/* ANA GRID — ilk ekranı doldurur (buton için yer bırakacak şekilde) */}
      <div className="grid grid-cols-12 gap-3 h-[calc(100vh-12rem)] min-h-[520px]">
        {/* SOL: grafikler */}
        <div className="col-span-12 lg:col-span-8 grid grid-rows-4 gap-3 min-h-0">
          <div className="panel rounded-lg clickable min-h-0" onClick={() => setModal('throughput')}>
            <MetricChart data={series} dataKey="throughput" color="#22d3ee" unit="Mbps" title="Throughput" domain={[0, 120]} />
          </div>
          <div className="panel rounded-lg clickable min-h-0" onClick={() => setModal('latency')}>
            <MetricChart data={series} dataKey="latency" color="#fbbf24" unit="ms" title="Latency" domain={[0, 'auto']} />
          </div>
          <div className="panel rounded-lg clickable min-h-0" onClick={() => setModal('snr')}>
            <MetricChart data={series} dataKey="snr" color="#34f5a8" unit="dB" title="SNR" domain={[-15, 30]} threshold={0} />
          </div>
          <div className="panel rounded-lg clickable min-h-0" onClick={() => setModal('combined')}>
            <CombinedChart data={series} />
          </div>
        </div>

        {/* SAĞ */}
        <div className="col-span-12 lg:col-span-4 grid grid-rows-[auto_auto_1fr] gap-3 min-h-0">
          {/* Status */}
          <div className={`panel rounded-lg p-4 border-2 ${meta_.ring} clickable`} onClick={() => setModal('status')}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-bold tracking-[0.25em] text-slate-500">BAĞLANTI DURUMU</span>
              <span className="text-[10px] text-slate-500">HO: {handoverCount} <span className="expand-hint text-cyan-400">⤢</span></span>
            </div>
            <div className={`font-display text-lg font-bold mb-1 ${meta_.glow}`} style={{ color: meta_.color }}>{meta_.label}</div>
            <div className="text-xs text-slate-400 mb-3 truncate">{statusText || '—'}</div>
            <StatusContent state={state} statusText={statusText} sat={sat} />
          </div>

          {/* Radar + tablo */}
          <div className="grid grid-cols-2 gap-3">
            <Panel title="Skyplot / Radar" onExpand={() => setModal('skyplot')}>
              <div className="flex items-center justify-center h-full">
                <Skyplot visible={visible} selectedSatnum={selectedSatnum} />
              </div>
            </Panel>
            <Panel title={`Görünür (${visible.length})`} onExpand={() => setModal('visible')}>
              <VisibleSatTable visible={visible} selectedSatnum={selectedSatnum} />
            </Panel>
          </div>

          {/* Log */}
          <div className="panel rounded-lg flex flex-col min-h-0 clickable" onClick={() => setModal('logs')}>
            <div className="flex items-center justify-between px-3 py-2 border-b border-[#16243f] shrink-0">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400 blink" />
                <h3 className="text-xs font-bold tracking-[0.2em] uppercase text-slate-300">Sistem Log Terminali</h3>
              </div>
              <span className="text-[10px] text-slate-600">{logs.length} kayıt <span className="expand-hint text-cyan-400">⤢</span></span>
            </div>
            <div className="flex-1 min-h-0"><LogTerminal logs={logs} /></div>
          </div>
        </div>
      </div>

      {/* ALT: buton — sticky, her zaman görünür kalır */}
      <div className="sticky bottom-0 z-20 flex justify-center items-center shrink-0 pt-2 pb-1"
           style={{ background: 'linear-gradient(to top, rgba(5,8,16,0.95) 40%, transparent)' }}>
        <button onClick={triggerDisaster} disabled={!isTerrestrial || busy}
          className={`font-display px-10 py-3.5 text-base font-black tracking-[0.15em] uppercase rounded-lg border-2 transition-all duration-150
            ${isTerrestrial && !busy
              ? 'bg-red-600/90 border-red-400 text-white hover:bg-red-500 hover:scale-105 active:scale-95 pulse-ring'
              : 'bg-[#0d1528] border-[#16243f] text-slate-600 cursor-not-allowed'}`}>
          ⚠ {isTerrestrial ? 'AFETİ TETİKLE — AĞI KOPAR' : `AFET MODU AKTİF · ${meta_.label}`} ⚠
        </button>
      </div>

      {/* FAZ 3: KANIT & DIŞA AKTARIM BÖLÜMÜ (sayfayı kaydır) */}
      <div className="grid grid-cols-12 gap-3 shrink-0 pb-2">
        {/* Handover timeline */}
        <div className="col-span-12 lg:col-span-7 panel rounded-lg flex flex-col clickable" onClick={() => setModal('timeline')} style={{ minHeight: 200 }}>
          <div className="flex items-center justify-between px-3 py-2 border-b border-[#16243f]">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-400" />
              <h3 className="text-xs font-bold tracking-[0.2em] uppercase text-slate-300">Handover Zaman Çizelgesi</h3>
            </div>
            <span className="text-[10px] text-slate-600">{timeline.length} geçiş <span className="expand-hint text-cyan-400">⤢</span></span>
          </div>
          <div className="flex-1 min-h-0 py-2">
            <HandoverTimeline events={timeline} />
          </div>
        </div>

        {/* Doğrulama + hesap + export araç paneli */}
        <div className="col-span-12 lg:col-span-5 panel rounded-lg flex flex-col p-4 gap-3" style={{ minHeight: 200 }}>
          <h3 className="text-xs font-bold tracking-[0.2em] uppercase text-slate-300">Kanıt & Doğrulama Araçları</h3>

          {/* n2yo canlı doğrulama */}
          <div className="bg-black/30 rounded p-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1">Bağımsız Doğrulama</div>
            {sat ? (
              <div className="text-xs text-slate-400">
                Şu an bağlı: <span className="text-cyan-300 font-bold">{sat.name}</span> (NORAD #{sat.satnum})
                <a href={`https://www.n2yo.com/?s=${sat.satnum}`} target="_blank" rel="noopener noreferrer"
                   onClick={(e) => e.stopPropagation()}
                   className="block mt-1 text-cyan-400 hover:text-cyan-300 underline">
                  → n2yo.com'da bu uydunun gerçek konumunu kontrol et
                </a>
                <div className="text-[10px] text-slate-600 mt-1">Elevasyon/azimut değerlerimizi canlı siteyle karşılaştırın.</div>
              </div>
            ) : (
              <div className="text-xs text-slate-600 italic">Bağlı uydu yok. Afeti tetikleyin.</div>
            )}
          </div>

          {/* Butonlar */}
          <div className="grid grid-cols-1 gap-2 mt-auto">
            <button onClick={() => setModal('linkbudget')}
                    className="text-xs px-3 py-2 rounded border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 transition text-left">
              🔬 Link Budget Hesabını Göster (SNR nereden geliyor?)
            </button>
            <div className="grid grid-cols-2 gap-2">
              <button onClick={() => downloadFile('/api/export/telemetry.csv')}
                      className="text-xs px-3 py-2 rounded border border-[#16243f] text-slate-400 hover:text-emerald-300 hover:border-emerald-500/50 transition">
                ⬇ Telemetri CSV
              </button>
              <button onClick={() => downloadFile('/api/export/session.json')}
                      className="text-xs px-3 py-2 rounded border border-[#16243f] text-slate-400 hover:text-emerald-300 hover:border-emerald-500/50 transition">
                ⬇ Oturum JSON
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* MODALLAR */}
      {modal === 'throughput' && <Modal title="THROUGHPUT — Mbps" onClose={() => setModal(null)}><MetricChart data={series} dataKey="throughput" color="#22d3ee" unit="Mbps" domain={[0, 120]} expanded /></Modal>}
      {modal === 'latency' && <Modal title="LATENCY — ms" onClose={() => setModal(null)}><MetricChart data={series} dataKey="latency" color="#fbbf24" unit="ms" domain={[0, 'auto']} expanded /></Modal>}
      {modal === 'snr' && <Modal title="SNR — dB" onClose={() => setModal(null)}><MetricChart data={series} dataKey="snr" color="#34f5a8" unit="dB" domain={[-15, 30]} threshold={0} expanded /></Modal>}
      {modal === 'combined' && <Modal title="BİRLEŞİK TELEMETRİ (sürükle = zoom)" onClose={() => setModal(null)}><CombinedChart data={series} expanded /></Modal>}
      {modal === 'status' && (
        <Modal title="BAĞLANTI DURUMU — DETAY" onClose={() => setModal(null)}>
          <div className={`font-display text-3xl font-bold mb-4 ${meta_.glow}`} style={{ color: meta_.color }}>{meta_.label}</div>
          <div className="text-slate-400 mb-1">{statusText}</div>
          <div className="text-slate-500 text-sm mb-6">Toplam handover: {handoverCount}</div>
          <StatusContent state={state} statusText={statusText} sat={sat} big />
        </Modal>
      )}
      {modal === 'skyplot' && (
        <Modal title="SKYPLOT / RADAR — TÜM GÖRÜNÜR UYDULAR" onClose={() => setModal(null)}>
          <div className="flex items-center justify-center h-full"><Skyplot visible={visible} selectedSatnum={selectedSatnum} expanded /></div>
        </Modal>
      )}
      {modal === 'visible' && (
        <Modal title={`GÖRÜNÜR UYDULAR (${visible.length}) — DETAY`} onClose={() => setModal(null)}>
          <VisibleSatTable visible={visible} selectedSatnum={selectedSatnum} expanded />
        </Modal>
      )}
      {modal === 'logs' && (
        <Modal title={`SİSTEM LOG TERMİNALİ — ${logs.length} KAYIT`} onClose={() => setModal(null)}>
          <LogTerminal logs={logs} expanded />
        </Modal>
      )}
      {modal === 'timeline' && (
        <Modal title={`HANDOVER ZAMAN ÇİZELGESİ — ${timeline.length} GEÇİŞ`} onClose={() => setModal(null)}>
          <HandoverTimeline events={timeline} expanded />
        </Modal>
      )}
      {modal === 'linkbudget' && (
        <Modal title="LINK BUDGET HESABI — ADIM ADIM" onClose={() => setModal(null)}>
          <LinkBudgetBreakdown data={lbData} />
        </Modal>
      )}
    </div>
  )
}
