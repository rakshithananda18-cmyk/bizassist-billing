import React from 'react'

const SLATE = 'var(--roadmap-ink, #8c9bac)'
const CLAY = '#d9997c'

function Tree({ x, y, scale = 1 }) {
  return <g transform={`translate(${x} ${y}) scale(${scale})`}>
    <ellipse cy="7" rx="20" ry="6" fill="#647a72" fillOpacity=".14" stroke="none" />
    <path d="M0 5v-29m0 14-8-7m8 2 8-7" stroke="#7f8d82" />
    <path d="M-15-19c-8-9-2-21 6-23 0-12 17-17 24-7 12 0 18 15 11 24 4 12-7 20-17 17-10 7-22 0-24-11Z" fill="#364b42" stroke="#778d7d" />
    <path d="M-9-33c2-5 7-8 12-8m7 13c4-1 6-4 7-8" stroke="#9bae98" strokeOpacity=".55" />
  </g>
}

function Lamp({ x, y, flip = false }) {
  return <g transform={`translate(${x} ${y}) scale(${flip ? -1 : 1} 1)`}>
    <ellipse cy="3" rx="9" ry="3" fill="#748294" fillOpacity=".12" stroke="none" />
    <path d="M0 1v-49c0-7 4-11 10-11h10m-24 60h8" />
    <path d="M13-59h17l-3 5H16Z" fill={CLAY} fillOpacity=".5" stroke={CLAY} />
    <path d="m15-49-9 23h31l-10-23" fill={CLAY} fillOpacity=".025" stroke="none" />
  </g>
}

function Shop({ x, y, width = 72, height = 82, accent = false, scale = 1 }) {
  const roof = -height
  return <g transform={`translate(${x} ${y}) scale(${scale})`}>
    <path d={`M-7 6h${width + 14}l21-11H14Z`} fill="#657282" fillOpacity=".09" stroke="none" />
    <path d={`M0 ${roof}h${width}V0H0Z`} fill="#26313b" />
    <path d={`m${width} ${roof} 18-11V-11L${width} 0Z`} fill="#1b232d" />
    <path d={`M0 ${roof}l18-11h${width}l-18 11Z`} fill="#3b4652" />
    <path d={`M-3 ${roof}v-5h${width + 6}v5Z`} fill="#465260" />
    <path d={`M12 ${roof + 16}h${width - 24}v15H12Z`} fill="#78939b" fillOpacity=".13" />
    <path d={`M${width / 2} ${roof + 16}v15`} strokeOpacity=".55" />
    <path d={`M9 -37h${width - 18}V0H9Z`} fill="#101820" />
    <path d="M21-36v36m-9-7h8" strokeOpacity=".7" />
    <path d={`M29 -28h${width - 46}v19H29Z`} fill="#8eaaad" fillOpacity=".12" strokeOpacity=".5" />
    <path d={`M-5-47h${width + 10}l-5 13H0Z`} fill={accent ? CLAY : '#6f8590'} fillOpacity=".45" stroke={accent ? CLAY : SLATE} />
    <path d={`M8-47 5-34m17-13-1 13m16-13 1 13m16-13 3 13`} stroke={accent ? '#eed2bb' : '#a1adb8'} strokeOpacity=".45" />
    <path d={`M${width - 12} -56H12`} stroke={accent ? CLAY : SLATE} strokeWidth="2.5" strokeOpacity=".5" />
  </g>
}

function Scooter({ x, y, angle = 0 }) {
  return <g transform={`translate(${x} ${y}) rotate(${angle})`}>
    <ellipse cx="18" cy="12" rx="31" ry="5" fill="#020407" fillOpacity=".45" stroke="none" />
    <circle cy="7" r="8" fill="#121b23" /><circle cx="38" cy="7" r="8" fill="#121b23" />
    <path d="M-5-2H9l11-14h10l3 20H7Z" fill={CLAY} fillOpacity=".45" stroke={CLAY} />
    <path d="m30-16-5-15h-9m9 0h7m-18 35h21M5-14h15" />
    <path d="M3-17h17v5H3Z" fill="#738190" />
    <circle cy="7" r="2" fill="#758391" stroke="none" /><circle cx="38" cy="7" r="2" fill="#758391" stroke="none" />
    <path d="M35-15h6v5h-6m-15 15-3 10" />
  </g>
}

function DeliveryVan({ x, y, angle = 0, scale = 1 }) {
  return <g transform={`translate(${x} ${y}) rotate(${angle}) scale(${scale})`}>
    <ellipse cx="43" cy="10" rx="48" ry="8" fill="#020407" fillOpacity=".55" stroke="none" />
    <path d="M0-29h53l11 9h13l14 17v11H0Z" fill="#77818d" fillOpacity=".52" />
    <path d="m0-29 10-7h50l-7 7m0 0 7-7 12 10-8 6m13 0 8-6L99-9 91-3m0 11 8-6V-9" fill="#465360" />
    <path d="M59-16h15L84-4H59Z" fill="#192b38" />
    <path d="M54-18V5m11-5h6M8-20h36M8-15h25" strokeOpacity=".55" />
    <path d="M8-5h32" stroke={CLAY} strokeWidth="3" strokeOpacity=".8" />
    <path d="M87 0h4v5h-4M0 0h3v5H0" fill={CLAY} stroke="none" />
    <circle cx="19" cy="8" r="8" fill="#10151c" /><circle cx="75" cy="8" r="8" fill="#10151c" />
    <circle cx="19" cy="8" r="3" fill="#667586" stroke="none" /><circle cx="75" cy="8" r="3" fill="#667586" stroke="none" />
  </g>
}

function Warehouse({ x, y, scale = 1 }) {
  return <g transform={`translate(${x} ${y}) scale(${scale})`}>
    <path d="m-27 103 48-30h207l-49 30Z" fill="#647482" fillOpacity=".08" stroke="none" />
    <path d="M0 0h176v90H0Z" fill="#27333f" />
    <path d="m176 0 38-28v90l-38 28Z" fill="#1d2833" />
    <path d="M0 0 38-28h176L176 0Z" fill="#3b4752" />
    <path d="m19-5 37-23m-1 23 37-23m-1 23 37-23m-1 23 37-23m-1 23 37-23" strokeOpacity=".35" />
    <path d="M-5 0h186v7H-5Z" fill={CLAY} fillOpacity=".4" stroke={CLAY} strokeOpacity=".65" />
    <path d="M21 35h75v55H21Z" fill="#131e28" />
    <path d="M26 43h65m-65 8h65m-65 8h65m-65 8h65m-65 8h65m-65 8h65" strokeOpacity=".32" />
    <path d="M113 47h39v43h-39Zm5-26h32v13h-32Z" fill="#76909a" fillOpacity=".13" />
    <path d="M139 68h5M0 17h176m-2 73h-65m70-70 28-20m-28 31 28-20" strokeOpacity=".45" />
    <path d="M11 94h94v7H11Z" fill="#465260" />
    <g transform="translate(179 96)" stroke="#9c8c7b">
      <path d="m0-18 13-7 15 7-13 8Zm0 0v18l15 8 13-8v-18m-13 8V8" fill="#67513f" fillOpacity=".25" />
      <path d="m28-10 12-6 13 6-12 7Zm0 0v16l13 7 12-7v-16m-12 7v16" fill="#67513f" fillOpacity=".2" />
    </g>
  </g>
}

/** Quiet roadside architecture; the centre and feature copy areas stay open. */
export default function RoadmapTown() {
  return <g className="roadmap-town" stroke={SLATE} strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" opacity=".42">
    <g strokeOpacity=".45">
      <path d="m25 760 78 1 18-9M28 768h74" />
      <path d="M88 783c-14 13-18 22-18 32" strokeDasharray="2 7" strokeOpacity=".4" />
    </g>
    <Shop x={38} y={754} scale={.7} accent />
    <Scooter x={57} y={832} angle={-4} />
    <g strokeOpacity=".65">
      <path d="m366 248 114 1 25-15M366 114l23-12h97m-120 153 119 1" />
    </g>
    <Shop x={380} y={231} width={76} height={110} scale={.8} accent />
    <Shop x={454} y={233} width={60} height={92} scale={.65} />
    <g transform="translate(365 235)" stroke="#809586">
      <path d="M0-8h11v10H0Z" fill="#334b3d" /><path d="M5-8v-9m0 7-5-5m5 2 6-7" />
    </g>
    <g transform="translate(494 239)" stroke="#809586">
      <path d="M0-8h13v11H0Z" fill="#334b3d" /><path d="M6-8v-10m0 6-5-4m5 0 5-7" />
    </g>
    <DeliveryVan x={299} y={283} angle={16} scale={.72} />
    <DeliveryVan x={1407} y={142} angle={-8} scale={.8} />

    <g stroke="#71867a">
      <path d="m374 823 67-28 48 15-66 29Z" fill="#30463c" fillOpacity=".25" />
      <path d="m374 823 1 9 48 16 66-29v-9m-66 29v9" strokeOpacity=".5" />
      <path d="m391 819 29-12m10 24 29-12" strokeOpacity=".5" />
    </g>
    <Tree x={461} y={115} scale={.7} />
    <Tree x={429} y={605} scale={.95} />
    <Tree x={151} y={752} scale={.7} />
    <Tree x={401} y={815} scale={.65} />
    <Tree x={463} y={809} scale={.72} />
    <Tree x={1590} y={301} scale={.8} />
    <Tree x={1531} y={690} scale={.95} />
    <Tree x={1167} y={792} scale={.85} />
    <Tree x={1487} y={886} scale={.85} />
    <Lamp x={456} y={367} flip />
    <Lamp x={1139} y={305} />
    <Lamp x={1520} y={155} flip />

    <g strokeOpacity=".4">
      <path d="m1301 350 38 4h213l28-16m-247 1h225M1537 188l-5 14" />
      <path d="M1279 274v14m-6-10h12" stroke={CLAY} strokeOpacity=".7" />
    </g>
    <Warehouse x={1330} y={237} />
    <DeliveryVan x={1360} y={339} scale={.76} />
    <DeliveryVan x={1474} y={333} scale={.76} />
    <g stroke="#82928a" transform="translate(1174 900)">
      <path d="m0-13 42 14-10 5-42-14Z" fill="#566452" fillOpacity=".2" />
      <path d="m-5-5-1 12m33-2-1 12m-31-29 42 14m-40-20 42 14" />
    </g>
    <Lamp x={1301} y={331} />
  </g>
}
