precision highp float;

/* ============================================================================
   GARGANTUA - Schwarzschild null-geodesic raytracer (pass 1)
   Integrates d2u/dphi2 = -u + 1.5 * rs * u^2 in the orbital plane of each ray,
   with Doppler beaming, gravitational redshift, procedural turbulence and a
   lensed procedural starfield / Milky Way. No meshes, textures or images.
   ========================================================================== */

out vec4 fragColor;

uniform vec2  uResolution;
uniform float uTime;
uniform vec3  uCamPos;
uniform mat3  uCamBasis;      /* columns: right, up, -forward */
uniform float uFovScale;      /* tan(0.5*fov) */
uniform float uRs;            /* Schwarzschild radius */
uniform float uDiskInner;     /* inner disk radius (ISCO ~ 3 rs) */
uniform float uDiskOuter;
uniform int   uSteps;
uniform float uStepScale;
uniform float uDiskTemp;
uniform float uDiskDensity;
uniform float uBeaming;
uniform float uRedshift;
uniform float uTurbulence;
uniform float uStarGain;
uniform float uNebula;
uniform float uGalaxyAmount;
uniform float uExposureScale;
uniform float uDopplerShift;  /* colour-shift strength */
uniform int   uDebug;
uniform float uPhiPhase;      /* disk pattern rotation */
uniform float uTimeScale;
uniform float uLensing;
uniform float uStarDensity;

#define PI 3.14159265358979
#define TAU 6.28318530717959
#define FAR 400.0

/* ------------------------------- hashing ---------------------------------- */
float hash11(float p){ p = fract(p*0.1031); p *= p+33.33; p *= p+p; return fract(p); }
float hash13(vec3 p){
  p = fract(p*0.1031); p += dot(p, p.zyx+31.32); return fract((p.x+p.y)*p.z);
}
vec3 hash33(vec3 p){
  p = vec3(dot(p,vec3(127.1,311.7,74.7)), dot(p,vec3(269.5,183.3,246.1)), dot(p,vec3(113.5,271.9,124.6)));
  return fract(sin(p)*43758.5453123);
}
float vnoise(vec3 x){
  vec3 i = floor(x), f = fract(x);
  f = f*f*(3.0-2.0*f);
  return mix(mix(mix(hash13(i+vec3(0,0,0)), hash13(i+vec3(1,0,0)), f.x),
                 mix(hash13(i+vec3(0,1,0)), hash13(i+vec3(1,1,0)), f.x), f.y),
             mix(mix(hash13(i+vec3(0,0,1)), hash13(i+vec3(1,0,1)), f.x),
                 mix(hash13(i+vec3(0,1,1)), hash13(i+vec3(1,1,1)), f.x), f.y), f.z);
}

/* --------------------------- blackbody palette ---------------------------- */
vec3 blackbody(float t){
  /* t = normalized temperature 0..~2 */
  t = max(t, 0.02);
  vec3 c;
  c.r = clamp( 56100000.0 * pow(t,3.0) + 43650000.0 * pow(t,2.0) + 1119000.0*t + 0.00396, 0.0, 1.0);
  c.g = clamp( 304500.0 * pow(t,3.0) + 6616000.0 * pow(t,2.0) - 84680.0*t + 0.56, 0.0, 1.0);
  if (t > 6500.0) {
    c.g = clamp( 195000000000.0*pow(t,4.0)+36100000000.0*pow(t,3.0)-13700000000.0*pow(t,2.0)+1223000.0*t+0.034, 0.0, 1.0);
    c.b = clamp( 148000000000.0*pow(t,4.0)+1520000000.0*pow(t,3.0)-13300000000.0*pow(t,2.0)+602200.0*t+0.00168, 0.0, 1.0);
  } else {
    c.b = clamp( 10400.0*pow(t,3.0)-166000.0*pow(t,2.0)+2013000.0*t - 17600.0, 0.0, 1.0);
  }
  return max(c, vec3(0.0));
}

/* ------------------------------ starfield -------------------------------- */
/* Deterministic cell star field over a fixed direction; returns colour. */
vec3 stars(vec3 dir){
  vec3 col = vec3(0.0);
  for (int layer = 0; layer < 3; layer++){
    float fl = float(layer);
    float scale = 220.0 * pow(2.3, fl);
    vec3 p = dir * scale;
    vec3 cell = floor(p);
    vec3 fr = p - cell;
    float density = step(hash13(cell + fl*17.17), uStarDensity);
    vec3 jitter = hash33(cell*1.37 + fl*7.77);
    vec3 sp = jitter*0.8 + 0.1 - fr;          /* star pos inside cell */
    float d = length(sp);
    float mag = hash11(hash13(cell)*91.7 + fl);
    float bright = pow(max(0.0, 1.0 - mag), 6.0) * 14.0;
    float core = exp(-d*d*scale*(0.06 + 0.05*jitter.x));
    float twinkle = 0.75 + 0.25*sin(uTime*(1.5+4.0*jitter.y) + jitter.z*TAU);
    float star = core*bright*density*twinkle;
    float temp = 2800.0 + 12000.0*pow(jitter.x, 2.2);
    col += star * blackbody(temp/6500.0);
  }
  return col * uStarGain;
}

/* Milky Way band: fbm nebula concentrated near a great circle. */
vec3 milkyWay(vec3 dir){
  vec3 n = normalize(vec3(0.28, 1.0, 0.16));       /* galactic plane normal */
  float band = 1.0 - abs(dot(dir, n));
  band = pow(clamp(band, 0.0, 1.0), 7.0);
  vec3 q = dir * 7.0;
  float f = 0.55*vnoise(q);
  f += 0.25*vnoise(q*2.3 + 11.0);
  f += 0.13*vnoise(q*5.1 + 23.0);
  f += 0.07*vnoise(q*10.3 + 41.0);
  float dust = smoothstep(0.35, 0.95, f);
  vec3 glow = mix(vec3(0.08,0.09,0.16), vec3(0.42,0.34,0.26), dust);
  vec3 dark = vec3(0.010, 0.011, 0.020);
  vec3 col = mix(glow, dark, smoothstep(0.55, 0.15, f)*0.85);
  float bulge = exp(-pow(abs(dot(dir, normalize(vec3(0.8,0.1,-0.58)))), 2.0)*7.0);
  col += vec3(0.22,0.19,0.14) * bulge * band;
  return col * band * uGalaxyAmount;
}

/* -------------------------- accretion disk body --------------------------- */
float diskAlphaProfile(float r){
  float a = smoothstep(uDiskInner, uDiskInner*1.06, r);
  float b = 1.0 - smoothstep(uDiskOuter*0.62, uDiskOuter, r);
  return a*b;
}

/* Keplerian angular velocity (geometric units rs=1): omega ~ r^-1.5 */
float keplerOmega(float r){ return 0.7071 / (r*sqrt(r)); }

/* Sample turbulent disk emission at a spacetime point.
   Returns HDR linear RGB (already includes emission falloff). */
vec3 sampleDisk(vec3 pos, float r){
  if (r < uDiskInner || r > uDiskOuter) return vec3(0.0);

  float omega = keplerOmega(r);
  /* advected coordinates so the pattern shears with rotation */
  float phase = omega * uTime * uTimeScale * uTurbulence;
  float cosP = cos(phase), sinP = sin(phase);
  vec2 rp = vec2(pos.x*cosP - pos.z*sinP, pos.x*sinP + pos.z*cosP);

  float ang = atan(rp.y, rp.x);
  vec3 q = vec3(rp*0.55, pos.y*2.2);

  /* spiral filaments: stretched noise along phi */
  float stretchAng = ang*3.0 + r*2.6;
  vec3 sq = vec3(stretchAng, r*1.15, pos.y*2.4);
  float t1 = vnoise(sq*2.0 + vec3(0.0, uTime*uTimeScale*0.25, 0.0));
  float t2 = vnoise(sq*4.7 + vec3(uTime*uTimeScale*0.4, 0.0, 3.7));
  float t3 = vnoise(sq*11.3 - vec3(0.0, 0.0, uTime*uTimeScale*0.8));
  float turb = t1*0.55 + t2*0.3 + t3*0.15;

  float filament = smoothstep(0.18, 0.82, turb + 0.28*sin(stretchAng*0.5 + r*3.0));
  float dens = mix(0.45, 1.15, filament) * uDiskDensity * diskAlphaProfile(r);

  /* radial temperature ~ r^-3/4 (Shakura-Sunyaev) */
  float tempNorm = uDiskTemp * pow((uDiskInner + 0.6)/max(r, 0.001), 0.75);
  vec3 emit = blackbody(max(0.08, tempNorm/6500.0));

  float thickness = exp(-abs(pos.y)*(2.6/r + 1.1)) ;
  float emis = dens * thickness * 7.5 / (r*r*0.12 + 1.0);
  return emit * emis;
}

/* photon-sphere capture shading for debug view 3 */
float horizonShade(float minR){ return smoothstep(uRs, uRs*2.2, minR); }

void main(){
  vec2 frag = gl_FragCoord.xy;
  vec2 uv = (frag - 0.5*uResolution) / uResolution.y;
  /* subpixel jitter for cheap AA; deterministic per frame */
  float fi = float(int(mod(uTime*60.0, 64.0)));
  uv += (hash33(vec3(frag, fi)).xy - 0.5) / uResolution.y * 0.9;

  vec3 rd = normalize(uCamBasis * normalize(vec3(uv*uFovScale, -1.0)));
  vec3 ro = uCamPos;

  vec3 col = vec3(0.0);
  float transmit = 1.0;
  bool captured = false;
  float minR = length(ro);
  int bounces = 0;

  /* integration state: position, direction, affine step */
  vec3 p = ro;
  vec3 v = rd;
  float totalOptical = 0.0;

  const int MAXSTEPS = 320;
  int steps = uSteps;

  for (int i = 0; i < MAXSTEPS; i++){
    if (i >= steps || transmit < 0.004) break;

    float r = length(p);
    minR = min(minR, r);

    if (r < uRs*0.98){ captured = true; break; }

    /* adaptive step: finer near the hole and inside the disk slab */
    float h = uStepScale * clamp(0.06*(r*r)/(uRs*3.0), 0.012, 1.2);
    bool inSlab = abs(p.y) < 0.75 && r < uDiskOuter*1.2;
    if (inSlab) h *= 0.35;

    /* --- RK2 midpoint on flat-space ray with gravitational bending --- */
    vec3 g1 = -1.5 * uRs * dot(v,v) * p / pow(max(r,1e-4), 4.0) * uLensing;
    vec3 pm = p + v*h*0.5;
    float rm = max(length(pm), 1e-4);
    vec3 vm = v + g1*h*0.5;
    vec3 g2 = -1.5 * uRs * dot(vm,vm) * pm / pow(rm, 4.0) * uLensing;
    vec3 pn = p + vm*h;
    vec3 vn = v + g2*h;

    /* renormalise to keep |v| ~ 1 (affine parametrisation approximation) */
    vn = normalize(vn);

    /* ---------- volumetric emission between p and pn ---------- */
    if (inSlab){
      const int SUBS = 4;
      for (int s = 0; s < SUBS; s++){
        float ts = (float(s)+0.5)/float(SUBS);
        vec3 sp = mix(p, pn, ts);
        float sr = length(sp);
        if (sr < uDiskInner || sr > uDiskOuter) continue;
        vec3 em = sampleDisk(sp, sr);
        if (em == vec3(0.0)) continue;

        /* ---- relativistic factors ---- */
        float speedInv = sqrt(1.0/(sr));          /* beta = sqrt(rs/2r) with rs=1 */
        vec3 orbitDir = normalize(cross(vec3(0.0,1.0,0.0), sp));
        /* flow direction: prograde */
        float dopplerDir = dot(normalize(v), orbitDir);
        float beta = 0.577 * speedInv * clamp(speedInv, 0.0, 1.0);
        float dopp = sqrt(1.0-beta*beta) / (1.0 - beta * (-dopplerDir));
        /* gravitational redshift */
        float grav = sqrt(max(1.0 - 1.0/sr, 0.02));
        float shift = mix(1.0, dopp * (1.0/grav), uRedshift);

        vec3 shifted = em * shift*shift*shift * mix(1.0, shift, uDopplerShift);
        shifted *= mix(1.0, pow(shift, 2.2), uBeaming*0.65);

        float sigma = dens0(sr) * uDiskDensity;
        float od = sigma * (h/float(SUBS));
        float a = exp(-od);
        col += transmit * shifted * (1.0 - a);
        transmit *= a;
      }
      if (transmit < 0.01){ captured = true; break; }  /* opaque -> stop tracing */
    }

    p = pn; v = vn;
    totalOptical += h;

    if (r > FAR && dot(p, v) > 0.0){
      /* escaped: lensed sky */
      break;
    }
    if (r < uRs*1.02){ captured = true; break; }
  }

  /* ---------------- sky lookup or horizon ------------------ */
  if (!captured && transmit > 0.002){
    vec3 skydir = normalize(v);
    vec3 sky = stars(skydir) + milkyWay(skydir);
    col += transmit * sky;
  }

  /* subtle fog toward the hole so the shadow stays deep but not pixel-flat */
  if (captured){
    col *= 0.985;                    /* residual bloom feed only */
    if (minR < uRs*1.02) col *= 0.55;
  }

  /* ------------------------- debug views ------------------- */
  if (uDebug != 0){
    float r0 = length(ro);
    if (uDebug == 1){                 /* raw geodesic bend heatmap */
      float bend = acos(clamp(dot(rd, normalize(v)), -1.0, 1.0)) / PI;
      fragColor = vec4(vec3(bend*2.4, 0.25 + captured ? 0.0 : 0.0, captured ? 0.0 : 0.1), 1.0);
      fragColor.rgb = vec3(bend*2.6, captured?1.0:0.0, 0.05+bend);
      return;
    }
    if (uDebug == 2){                 /* escape/capture mask */
      fragColor = vec4(captured ? vec3(0.9,0.1,0.05) : vec3(0.05,0.4,0.9), 1.0);
      return;
    }
    if (uDebug == 3){                 /* closest approach */
      float t = clamp((minR-uRs)/(uRs*3.0), 0.0, 1.0);
      fragColor = vec4(vec3(t), 1.0);
      return;
    }
    if (uDebug == 4){                 /* doppler only */
      fragColor = vec4(col/max(dot(col,vec3(0.333)),1e-3)*min(length(col),1.4), 1.0);
      return;
    }
    if (uDebug == 5){                 /* temperature map */
      float tr = clamp((length(ro)-uDiskInner)/(uDiskOuter-uDiskInner),0.0,1.0);
      fragColor = vec4(blackbody(mix(1.3,0.35,tr)), 1.0);
      return;
    }
    if (uDebug == 6){                 /* iterate count */
      fragColor = vec4(vec3(float(steps)/320.0), 0.4, 0.15, 1.0);
      return;
    }
    if (uDebug == 7){                 /* UV / radial grid of lensed sky */
      vec3 sd = normalize(v);
      float th = atan(sd.y, sd.x)/(2.0*PI)+0.5;
      float ph = asin(clamp(sd.z,-1.0,1.0))/PI+0.5;
      vec2 g = abs(fract(vec2(th,ph)*16.0)-0.5);
      float lines = smoothstep(0.47,0.5,max(g.x,g.y));
      fragColor = vec4(lines*vec3(0.2,0.8,0.9)+sd*0.1, 1.0);
      return;
    }
    if (uDebug == 8){                 /* optical depth */
      fragColor = vec4(vec3(1.0-transmit), 1.0);
      return;
    }
    if (uDebug == 9){                 /* luminance isolines of raw colour */
      float l = log2(max(dot(col, vec3(0.2126,0.7152,0.0722)), 1e-5))*0.35+8.0;
      fragColor = vec4(mix(vec3(0.0), vec3(0.1,1.0,0.4), fract(l)) , 1.0);
      return;
    }
  }

  fragColor = vec4(col * uExposureScale, 1.0);
}

float dens0(float r){
  return diskAlphaProfile(r) * 1.2 / (0.06*r*r + 1.0);
}
