// GARGANTUA — GLSL programs. Scene pass integrates Schwarzschild null geodesics
// (velocity-Verlet on the exact Cartesian form  a = -3 h² x / r⁵  in M-units,
// r_s = 2M, photon sphere 3M, ISCO 6M). All output is linear HDR.

export const VERT = /* glsl */`
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

const DEFS = `
#define PI 3.141592653589793
#define ESC_R 46.0
`;

const LIB = /* glsl */`
float hash11(float p){ p = fract(p*0.1031); p *= p+33.33; p *= p+p; return fract(p); }
vec3 hash33(vec3 p){
  p = fract(p*vec3(0.1031,0.1030,0.0973));
  p += dot(p, p.yxz+33.33);
  return fract((p.xxy+p.yxx)*p.zyx);
}
float vnoise(vec3 p){
  vec3 i = floor(p), f = fract(p);
  f = f*f*(3.0-2.0*f);
  float n = mix(
    mix(mix(hash33(i+vec3(0,0,0)).x, hash33(i+vec3(1,0,0)).x, f.x),
        mix(hash33(i+vec3(0,1,0)).x, hash33(i+vec3(1,1,0)).x, f.x), f.y),
    mix(mix(hash33(i+vec3(0,0,1)).x, hash33(i+vec3(1,0,1)).x, f.x),
        mix(hash33(i+vec3(0,1,1)).x, hash33(i+vec3(1,1,1)).x, f.x), f.y), f.z);
  return n*n*(3.0-2.0*n)*2.0-0.30;   // centered, zero-mean-ish
}
float fbm(vec3 p){
  float a = 0.52, s = 0.0, norm = 0.0;
  for(int i=0;i<5;i++){ s += a*vnoise(p); norm += a; p = p*2.03 + 17.13; a *= 0.52; }
  return s/norm;
}
// Planckian locus approximation (Kelvin -> linear sRGB-ish)
vec3 blackbody(float K){
  float t = clamp(K, 1200.0, 22000.0)*0.01;
  float r = t<=66.0 ? 1.0 : clamp(1.29294*pow(t-60.0,-0.1332047), 0.0, 1.0);
  float g = t<=66.0 ? clamp(0.39008*log(t)-0.63184, 0.0, 1.0)
                    : clamp(1.12989*pow(t-60.0,-0.0755148), 0.0, 1.0);
  float b = t>=66.0 ? 1.0 : (t<=19.0 ? 0.0 : clamp(0.54320*log(t-10.0)-1.19625, 0.0, 1.0));
  return vec3(r,g,b);
}
mat3 rotY(float a){ float c=cos(a),s=sin(a); return mat3(c,0.,-s, 0.,1.,0., s,0.,c); }
`;

const SKY = /* glsl */`
uniform float uStarGain, uMilkyGain;

float starLayer(vec3 d, float scale, float gain){
  vec3 p = d*scale;
  vec3 c = floor(p);
  float m = 0.0;
  for(int x=-1;x<=1;x++) for(int y=-1;y<=1;y++) for(int z=-1;z<=1;z++){
    vec3 o = vec3(float(x),float(y),float(z));
    vec3 h = hash33(c+o);
    float mag = pow(h.y, 22.0);                 // sparse bright stars
    if(mag < 1e-4) continue;
    vec3 sp = c + o + 0.15 + 0.7*h;
    float dd = length(p - sp);
    m += exp(-dd*dd*(140.0+240.0*h.z)) * mag;
  }
  return m*gain;
}

vec3 skyColor(vec3 d){
  float st = starLayer(d, 34.0, 1.0)*1.5 + starLayer(d+vec3(7.31), 71.0, 0.55)*0.9
           + starLayer(d.zxy+vec3(3.7), 143.0, 0.30)*0.55;
  vec3 scol = vec3(0.78,0.85,1.0)*st + vec3(1.0,0.86,0.70)*starLayer(d.yzx+vec3(11.2),57.0,0.42);

  vec3 pole = normalize(vec3(0.32,0.86,0.39));
  vec3 core = normalize(vec3(-0.78,0.10,0.61));
  float band = exp(-pow(dot(d,pole)*2.35, 2.0)*3.2);
  float cloud = fbm(d*3.1+vec3(4.7))*0.5+0.5;
  float lanes = smoothstep(0.42,0.78, fbm(d*6.3+vec3(9.1))*0.5+0.5);
  float mw = band*(0.30+0.85*cloud)*(1.0-0.75*lanes);
  float coreGlow = pow(max(dot(d,core),0.0), 7.0)*band;
  vec3 mcol = mix(vec3(0.36,0.42,0.62), vec3(0.95,0.80,0.60), coreGlow*1.6+cloud*0.22);
  return (scol*1.15 + mcol*mw*1.35 + vec3(0.50,0.62,1.0)*coreGlow*0.55)
         * vec3(uStarGain*0.55+0.45) * vec3(1.0, 1.0, 1.05)
         + vec3(0.010,0.012,0.020);              // deep-space ambient floor
}
`;

const SCENE_BODY = /* glsl */`
uniform vec2  uRes;
uniform float uTime, uTanFov, uSteps, uDbg, uSeed, uAspect;
uniform vec3  uCamPos, uCamRight, uCamUp, uCamFwd;
uniform float uDiskDensity,uDiskInner,uDiskOuter,uDiskThick,uDiskTemp,
              uSpinSpeed,uTurbScale,uTurbGain,uDopplerAmt,uGravRedshift;
varying vec2 vUv;

${LIB}
${SKY}

void diskEmit(vec3 p, vec3 vel, float dt, inout vec3 acc, inout float trans,
              inout float gLast){
  float r = length(p.xz);
  float ri = uDiskInner, ro = uDiskOuter;
  if(r < ri || r > ro || trans < 0.004) return;
  float fr = (r-ri)/max(ro-ri, 1e-3);
  float H = uDiskThick*(0.30+0.85*fr) * (0.5+0.5*ri/r);
  float prof = exp(-0.5*(p.y/H)*(p.y/H));
  if(prof < 0.004) return;

  float ang = atan(p.z, p.x);
  float omega = 0.55*uSpinSpeed*pow(max(r,0.8), -1.5);
  vec3 rp = rotY(uTime*omega*6.0) * p;               // differential Keplerian shear
  float turb = fbm(vec3(rp.x, rp.z, p.y*2.6)*uTurbScale*0.55)*0.5+0.5;
  float streak = fbm(vec3(r*1.7, ang*2.0 + rp.x*0.20, p.y*4.0)*1.6)*0.5+0.5;
  float dens = prof * uDiskDensity *
      (0.22 + uTurbGain*(0.65*turb + 0.55*streak));

  float fall = pow(ri/r, 2.1);
  dens *= fall * smoothstep(ro, ro*0.70, r) * smoothstep(ri, ri*1.12, r) * 2.6;
  if(dens <= 0.0) return;

  float beta = clamp(inversesqrt(max(2.0*(r-1.0), 0.45)), 0.0, 0.985); // v/c, ISCO=0.5
  float gam  = inversesqrt(1.0-beta*beta);
  vec3 tangent = normalize(vec3(-p.z, 0.0, p.x));
  vec3 kphoton = -normalize(vel);
  float gd = 1.0/(gam*(1.0 - beta*dot(tangent,kphoton)));
  float gg = sqrt(max(1.0-1.0/r, 0.02));
  float g = mix(1.0, gd, uDopplerAmt) * mix(1.0, gg, uGravRedshift);
  gLast = g;

  float T = uDiskTemp * pow(ri/r, 0.75) * g;
  vec3 e = blackbody(T) * pow(max(g,0.02), 3.0);
  float e2 = dens*dt;
  acc   += e * e2 * trans * 2.35;
  trans *= exp(-dens*dt*1.35);
}

void main(){
  vec2 frag = vUv*uRes;
  vec2 jit = vec2(hash11(frag.x*12.9898+uSeed), hash11(frag.y*78.233+uSeed)) - 0.5;
  vec2 ndc = (frag+jit)/uRes*2.0 - 1.0;
  vec3 rd = normalize(uCamFwd + uCamRight*ndc.x*uTanFov*uAspect + uCamUp*ndc.y*uTanFov);
  vec3 p  = uCamPos;
  vec3 v  = rd;
  vec3 hv = cross(p, v);
  float h2 = dot(hv, hv);

  vec3 acc = vec3(0.0);
  float trans = 1.0, minR = 1e4, gLast = 1.0, bend = 0.0;
  bool captured = false, escaped = false;
  float stepsUsed = 0.0;
  float prevY = p.y;

  for(int i=0;i<MAX_STEPS_LOOP;i++){
    if(float(i) >= uSteps){ escaped = false; break; }
    stepsUsed = float(i);
    float r = length(p);
    minR = min(minR, r);
    if(r < 1.02){ captured = true; break; }
    if(r > ESC_R && dot(p,v) > 0.0){ escaped = true; break; }

    float planeProx = exp(-p.y*p.y*10.0)
        * smoothstep(uDiskInner-2.5, uDiskInner, length(p.xz))
        * smoothstep(uDiskOuter+3.0, uDiskOuter, length(p.xz));
    float dt = clamp(0.05 + 0.16*(r-1.0), 0.022, 1.15) * mix(1.0, 0.40, planeProx);
    if(r < 3.2) dt = min(dt, 0.06 + 0.05*(r-1.0));

    vec3 a1 = -1.5*h2*p/pow(dot(p,p), 2.5);
    vec3 pn = p + v*dt + 0.5*a1*dt*dt;
    vec3 a2 = -1.5*h2*pn/pow(dot(pn,pn), 2.5);
    vec3 vn = v + 0.5*(a1+a2)*dt;

    bend += length(a2)*dt;
    if(planeProx > 0.02){
      diskEmit(pn, vn, dt, acc, trans, gLast);
    } else if(prevY*pn.y < 0.0){                     // thin-slab crossing guard
      for(int s=1;s<=3;s++){
        float f = float(s)/3.0;
        vec3 q = mix(p, pn, f);
        diskEmit(q, normalize(mix(v,vn,f)), dt/3.0, acc, trans, gLast);
      }
    }
    prevY = pn.y;
    p = pn; v = vn;
  }

  vec3 col;
  vec3 dirOut = normalize(v);
  if(captured){
    col = acc + vec3(0.0);
  } else {
    vec3 sky = escaped ? skyColor(dirOut) : vec3(0.0);
    float ring = exp(-pow((minR-1.5)*7.0, 2.0));
    col = acc + sky*trans + vec3(0.30,0.42,0.85)*ring*0.10*trans*(0.4+0.6*uDopplerAmt);
  }

  float dbg = floor(uDbg+0.5);
  if(dbg == 1.0) col = vec3(max(max(col.r,col.g),col.b));                       // HDR lum
  else if(dbg == 2.0) col = vec3(pow(stepsUsed/uSteps, 0.5), stepsUsed/uSteps*0.6, 0.15);
  else if(dbg == 3.0) col = blackbody(mix(2500.0, 14000.0, clamp((gLast-0.4)/1.4,0.0,1.0)))
                             * (acc.r+acc.g+acc.b > 0.0 ? 1.0 : 0.06);
  else if(dbg == 4.0) col = vec3(clamp((acc.r+acc.g+acc.b)*0.8, 0.0, 1.0));
  else if(dbg == 5.0) col = vec3(pow(clamp(bend*0.16,0.0,1.0), 0.7))*vec3(1.0,0.55,0.25);
  else if(dbg == 6.0) col = escaped ? dirOut*0.5+0.5 : vec3(0.0);
  else if(dbg == 7.0) col = vec3(exp(-pow((minR-1.5)*9.0, 2.0)));
  else if(dbg == 8.0) col = captured ? vec3(1.0,0.2,0.1) : vec3(0.02,0.05,0.09);
  else if(dbg == 9.0) col = escaped ? skyColor(dirOut) : vec3(0.0);

  gl_FragColor = vec4(col, 1.0);
}
`;

export const FRAG_SCENE = DEFS + SCENE_BODY;

/* ---------------- post chain (HDR -> bloom -> ACES composite) ------------- */

export const FRAG_BRIGHT = /* glsl */`
uniform sampler2D tSrc; uniform vec2 uTexel; uniform float uThreshold;
varying vec2 vUv;
void main(){
  vec3 c = texture2D(tSrc, vUv).rgb;
  float l = dot(c, vec3(0.2126,0.7152,0.0722));
  float knee = uThreshold*0.4;
  float w = smoothstep(uThreshold-knee, uThreshold+knee, l);
  gl_FragColor = vec4(c*w, 1.0);
}
`;

const BLUR = /* glsl */`
uniform sampler2D tSrc; uniform vec2 uTexel; uniform vec2 uDir; uniform float uRadius;
varying vec2 vUv;
void main(){
  vec2 o = uDir*uTexel*uRadius;
  vec3 s = texture2D(tSrc, vUv).rgb*0.227027;
  s += (texture2D(tSrc, vUv+o*1.3846).rgb + texture2D(tSrc, vUv-o*1.3846).rgb)*0.316216;
  s += (texture2D(tSrc, vUv+o*3.2308).rgb + texture2D(tSrc, vUv-o*3.2308).rgb)*0.070270;
  gl_FragColor = vec4(s, 1.0);
}
`;
export const FRAG_BLUR = BLUR;

export const FRAG_COMPOSITE = /* glsl */`
uniform sampler2D tScene, tBloom;
uniform vec2 uRes;
uniform float uTime,uBloomStr,uExposureEV,uGrain,uAberr,uVignette,uBlackFloor,uSeed;
varying vec2 vUv;

vec3 aces(vec3 x){
  const float a=2.51,b=0.03,c=2.43,d=0.59,e=0.14;
  return clamp((x*(a*x+b))/(x*(c*x+d)+e), 0.0, 1.0);
}
float grain(vec2 uv, float t){
  vec3 h = vec3(uv, fract(t))*vec3(443.897,441.423,437.195);
  return fract(sin(dot(h, vec3(12.9898,78.233,37.719)))*43758.5453);
}
void main(){
  vec2 uv = vUv;
  vec2 d = uv-0.5;
  float r2 = dot(d,d);
  float ab = uAberr*0.0035*r2;
  vec3 c;
  c.r = texture2D(tScene, uv-d*ab).r;
  c.g = texture2D(tScene, uv).g;
  c.b = texture2D(tScene, uv+d*ab).b;
  vec3 bl = texture2D(tBloom, uv).rgb;
  c += bl*uBloomStr;

  c *= exp2(uExposureEV);
  c = aces(c);
  c = pow(c, vec3(1.0/2.2));

  float vig = 1.0 - uVignette*smoothstep(0.18, 0.92, sqrt(r2)*1.414);
  c *= vig;
  c += (grain(uv*uRes, uTime+uSeed)-0.5)*uGrain*(0.35+0.65*(1.0-c));
  c = c*(1.0-uBlackFloor) + uBlackFloor;
  gl_FragColor = vec4(clamp(c,0.0,1.0), 1.0);
}
`;

export function patchScene(src, maxSteps){
  return src.replace('__DEFS__', '')
            .replace('#define ESC_R', `#define MAX_STEPS_LOOP ${maxSteps|0}\n#define ESC_R`);
}
