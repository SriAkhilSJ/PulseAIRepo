// GARGANTUA — shared uniforms, quality profiles, presets (pure data + tiny math).
export const QUALITY = {
  low:  { steps: 96,  extra: 0, sub: 1.00, resScale: 0.62, label: 'LOW'  },
  med:  { steps: 192, extra: 0, sub: 1.00, resScale: 0.80, label: 'MED'  },
  high: { steps: 320, extra: 2, sub: 2.00, subOn: true, resScale: 1.00, label: 'HIGH' }
};

// 21 live parameters — every one is a real uniform read by the shader.
export const PARAM_DEFS = [
  ['diskDensity',   'disk density',      0.0, 3.0, 0.01, 1.30],
  ['diskInner',     'disk inner r',      3.0, 9.0, 0.05, 6.0],
  ['diskOuter',     'disk outer r',     10.0,26.0, 0.25, 15.5],
  ['diskThick',     'disk thickness',    0.02,0.60,0.01, 0.16],
  ['diskTemp',      'temperature K',   2000,14000,100,  7200],
  ['spinSpeed',     'turbulence speed',  0.0, 2.0, 0.01, 0.55],
  ['turbScale',     'turbulence scale',  0.5, 8.0, 0.05, 2.6],
  ['turbGain',      'turbulence gain',   0.0, 2.0, 0.01, 0.85],
  ['starGain',      'star gain',         0.0, 2.5, 0.01, 1.0],
  ['milkyGain',     'milky way gain',    0.0, 2.0, 0.01, 0.55],
  ['dopplerAmt',    'Doppler beaming',   0.0, 1.0, 0.01, 0.92],
  ['gravRedshift',  'redshift',          0.0, 1.0, 0.01, 1.0],
  ['bloomStrength', 'bloom strength',    0.0, 2.0, 0.01, 0.62],
  ['bloomRadius',   'bloom radius',      0.4, 2.4, 0.01, 0.95],
  ['exposure',      'exposure EV',      -2.5, 2.5, 0.05, 0.55],
  ['grainAmt',      'film grain',        0.0, 0.20,0.002,0.035],
  ['aberration',    'chromatic aberr.',  0.0, 3.0, 0.01, 0.75],
  ['vignette',      'vignette',          0.0, 1.5, 0.01, 0.72],
  ['blackFloor',    'black floor',       0.0, 0.06,0.001,0.004],
  ['timeWarp',      'time dilation fx',  0.0, 2.0, 0.01, 1.0],
  ['camFov',        'camera FOV°',      22.0,100.0,0.5,  52.0]
];

export function defaultParams(){
  const o = {};
  for (const [k,,,,,v] of PARAM_DEFS) o[k] = v;
  return o;
}

export const PRESETS = {
  interstellar: {
    name:'INTERSTELLAR',
    p:{ diskDensity:1.35,diskInner:6.0,diskOuter:15.5,diskThick:0.16,diskTemp:7200,
        spinSpeed:0.55,turbScale:2.6,turbGain:0.85,starGain:1.0,milkyGain:0.55,
        dopplerAmt:0.92,gravRedshift:1.0,bloomStrength:0.62,bloomRadius:0.95,
        exposure:0.55,grainAmt:0.035,aberration:0.75,vignette:0.72,blackFloor:0.004,
        timeWarp:1.0,camFov:52.0 }
  },
  photon: {
    name:'PHOTON RING',
    p:{ diskDensity:0.55,diskInner:6.0,diskOuter:13.0,diskThick:0.07,diskTemp:9500,
        spinSpeed:0.18,turbScale:3.4,turbGain:0.45,starGain:0.8,milkyGain:0.28,
        dopplerAmt:0.55,gravRedshift:1.0,bloomStrength:1.15,bloomRadius:0.65,
        exposure:0.85,grainAmt:0.03,aberration:1.25,vignette:0.55,blackFloor:0.002,
        timeWarp:1.0,camFov:38.0 }
  },
  edgeon: {
    name:'EDGE-ON BLADE',
    p:{ diskDensity:1.7,diskInner:6.0,diskOuter:17.5,diskThick:0.05,diskTemp:6400,
        spinSpeed:0.75,turbScale:3.8,turbGain:1.15,starGain:0.7,milkyGain:0.4,
        dopplerAmount:undefined,dopplerAmt:1.0,gravRedshift:1.0,bloomStrength:0.5,
        bloomRadius:1.25,exposure:0.3,grainAmt:0.04,aberration:1.6,vignette:0.85,
        blackFloor:0.006,timeWarp:1.0,camFov:46.0 }
  },
  abyss: {
    name:'ABYSS',
    p:{ diskDensity:0.22,diskInner:7.0,diskOuter:11.0,diskThick:0.30,diskTemp:3800,
        spinSpeed:0.12,turbScale:1.6,turbGain:0.55,starGain:1.6,milkyGain:1.15,
        dopplerAmt:0.35,gravRedshift:1.0,bloomStrength:0.42,bloomRadius:1.35,
        exposure:0.15,grainAmt:0.055,aberration:0.4,vignette:1.05,blackFloor:0.010,
        timeWarp:0.6,camFov:58.0 }
  }
};

export const CAMERA_PATHS = [
  { id:'orbit',    name:'ORBIT (free)' },
  { id:'slowspin', name:'CINEMATIC · SLOW SPIN' },
  { id:'grazing',  name:'CINEMATIC · GRAZING PASS' },
  { id:'plunge',   name:'CINEMATIC · PLUNGE & RECOIL' },
  { id:'rise',     name:'CINEMATIC · RISE OVER DISK' }
];
