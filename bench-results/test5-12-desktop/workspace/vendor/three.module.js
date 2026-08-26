/* Minimal local Three.js-compatible runtime (math, camera, clock, WebGL2 renderer
   tuned for full-screen shader pipelines). ES module, no build step required. */

export const REVISION = '127-gargantua-local';

/* ------------------------------ math utils ------------------------------- */
export const MathUtils = {
  degToRad: (d) => d * Math.PI / 180,
  radToDeg: (r) => r * 180 / Math.PI,
  clamp: (v, a, b) => Math.max(a, Math.min(b, v)),
  lerp: (a, b, t) => a + (b - a) * t,
  damp: (a, b, lambda, dt) => MathUtils.lerp(a, b, 1 - Math.exp(-lambda * dt)),
};

export class EventDispatcher {
  addEventListener(type, fn) {
    if (!this._listeners) this._listeners = {};
    (this._listeners[type] ||= []).push(fn);
  }
  removeEventListener(type, fn) {
    const arr = this._listeners && this._listeners[type];
    if (!arr) return;
    const i = arr.indexOf(fn);
    if (i >= 0) arr.splice(i, 1);
  }
  dispatchEvent(event) {
    const arr = this._listeners && this._listeners[event.type];
    if (arr) for (const fn of arr.slice()) fn.call(this, event);
  }
}

export class Vector2 {
  constructor(x = 0, y = 0) { this.x = x; this.y = y; }
  set(x, y) { this.x = x; this.y = y; return this; }
  copy(v) { this.x = v.x; this.y = v.y; return this; }
  clone() { return new Vector2(this.x, this.y); }
  add(v) { this.x += v.x; this.y += v.y; return this; }
  sub(v) { this.x -= v.x; this.y -= v.y; return this; }
  multiplyScalar(s) { this.x *= s; this.y *= s; return this; }
  divideScalar(s) { const i = 1 / (s || 1); this.x *= i; this.y *= i; return this; }
  length() { return Math.sqrt(this.x * this.x + this.y * this.y); }
  lengthSq() { return this.x * this.x + this.y * this.y; }
  normalize() { return this.divideScalar(this.length() || 1); }
  min(v) { this.x = Math.min(this.x, v.x); this.y = Math.min(this.y, v.y); return this; }
  max(v) { this.x = Math.max(this.x, v.x); this.y = Math.max(this.y, v.y); return this; }
}

export class Vector3 {
  constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
  set(x, y, z) { this.x = x; this.y = y; this.z = z; return this; }
  copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this; }
  clone() { return new Vector3(this.x, this.y, this.z); }
  add(v) { this.x += v.x; this.y += v.y; this.z += v.z; return this; }
  sub(v) { this.x -= v.x; this.y -= v.y; this.z -= v.z; return this; }
  addScaledVector(v, s) { this.x += v.x * s; this.y += v.y * s; this.z += v.z * s; return this; }
  multiplyScalar(s) { this.x *= s; this.y *= s; this.z *= s; return this; }
  divideScalar(s) { const i = 1 / (s || 1); this.x *= i; this.y *= i; this.z *= i; return this; }
  negate() { return this.multiplyScalar(-1); }
  dot(v) { return this.x * v.x + this.y * v.y + this.z * v.z; }
  cross(v) { return this.crossVectors(this, v); }
  crossVectors(a, b) {
    const ax = a.x, ay = a.y, az = a.z, bx = b.x, by = b.y, bz = b.z;
    this.x = ay * bz - az * by;
    this.y = az * bx - ax * bz;
    this.z = ax * by - ay * bx;
    return this;
  }
  lengthSq() { return this.dot(this); }
  length() { return Math.sqrt(this.lengthSq()); }
  normalize() { return this.divideScalar(this.length() || 1); }
  distanceTo(v) { return Math.sqrt((this.x - v.x) ** 2 + (this.y - v.y) ** 2 + (this.z - v.z) ** 2); }
  lerp(v, t) { this.x += (v.x - this.x) * t; this.y += (v.y - this.y) * t; this.z += (v.z - this.z) * t; return this; }
  setFromSphericalCoords(r, phi, theta) {
    const sp = Math.sin(phi);
    this.set(r * sp * Math.sin(theta), r * Math.cos(phi), r * sp * Math.cos(theta));
    return this;
  }
}

export class Vector4 {
  constructor(x = 0, y = 0, z = 0, w = 1) { this.x = x; this.y = y; this.z = z; this.w = w; }
  copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; this.w = v.w; return this; }
  set(x, y, z, w) { this.x = x; this.y = y; this.z = z; this.w = w; return this; }
}

export class Quaternion {
  constructor(x = 0, y = 0, z = 0, w = 1) { this.x = x; this.y = y; this.z = z; this.w = w; }
  copy(q) { this.x = q.x; this.y = q.y; this.z = q.z; this.w = q.w; return this; }
  setFromRotationMatrix(m) {
    const e = m.elements;
    const m11 = e[0], m12 = e[4], m13 = e[8];
    const m21 = e[1], m22 = e[5], m23 = e[9];
    const m31 = e[2], m32 = e[6], m33 = e[10];
    const trace = m11 + m22 + m33;
    if (trace > 0) {
      const s = 0.5 / Math.sqrt(trace + 1.0);
      this.w = 0.25 / s; this.x = (m32 - m23) * s; this.y = (m13 - m31) * s; this.z = (m21 - m12) * s;
    } else if (m11 > m22 && m11 > m33) {
      const s = 2.0 * Math.sqrt(1.0 + m11 - m22 - m33);
      this.w = (m32 - m23) / s; this.x = 0.25 * s; this.y = (m12 + m21) / s; this.z = (m13 + m31) / s;
    } else if (m22 > m33) {
      const s = 2.0 * Math.sqrt(1.0 + m22 - m11 - m33);
      this.w = (m13 - m31) / s; this.x = (m12 + m21) / s; this.y = 0.25 * s; this.z = (m23 + m32) / s;
    } else {
      const s = 2.0 * Math.sqrt(1.0 + m33 - m11 - m22);
      this.w = (m21 - m12) / s; this.x = (m13 + m31) / s; this.y = (m23 + m32) / s; this.z = 0.25 * s;
    }
    return this.normalize();
  }
  normalize() {
    const len = Math.hypot(this.x, this.y, this.z, this.w) || 1;
    this.x /= len; this.y /= len; this.z /= len; this.w /= len;
    return this;
  }
}

export class Matrix4 {
  constructor() { this.elements = new Float32Array([1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]); }
  identity() { const e = this.elements; e.fill(0); e[0] = e[5] = e[10] = e[15] = 1; return this; }
  copy(m) { this.elements.set(m.elements); return this; }
  makeBasis(xAxis, yAxis, zAxis) {
    const e = this.elements;
    e[0] = xAxis.x; e[4] = yAxis.x; e[8]  = zAxis.x;
    e[1] = xAxis.y; e[5] = yAxis.y; e[9]  = zAxis.y;
    e[2] = xAxis.z; e[6] = yAxis.z; e[10] = zAxis.z;
    return this;
  }
  setPosition(x, y, z) {
    const e = this.elements;
    if (x.isVector3) { e[12] = x.x; e[13] = x.y; e[14] = x.z; }
    else { e[12] = x; e[13] = y; e[14] = z; }
    return this;
  }
  compose(position, quaternion, scale) {
    const e = this.elements;
    const x = quaternion.x, y = quaternion.y, z = quaternion.z, w = quaternion.w;
    const x2 = x + x, y2 = y + y, z2 = z + z;
    const xx = x * x2, xy = x * y2, xz = x * z2;
    const yy = y * y2, yz = y * z2, zz = z * z2;
    const wx = w * x2, wy = w * y2, wz = w * z2;
    const sx = scale.x, sy = scale.y, sz = scale.z;
    e[0] = (1 - (yy + zz)) * sx; e[4] = (xy - wz) * sy;       e[8]  = (xz + wy) * sz;
    e[1] = (xy + wz) * sx;       e[5] = (1 - (xx + zz)) * sy; e[9]  = (yz - wx) * sz;
    e[2] = (xz - wy) * sx;       e[6] = (yz + wx) * sy;       e[10] = (1 - (xx + yy)) * sz;
    e[12] = position.x; e[13] = position.y; e[14] = position.z;
    return this;
  }
  invert() {
    const e = this.elements;
    const n11 = e[0], n21 = e[1], n31 = e[2], n41 = e[3];
    const n12 = e[4], n22 = e[5], n32 = e[6], n42 = e[7];
    const n13 = e[8], n23 = e[9], n33 = e[10], n43 = e[11];
    const n14 = e[12], n24 = e[13], n34 = e[14], n44 = e[15];
    const t11 = n23 * n34 * n42 - n24 * n33 * n42 + n24 * n32 * n43 - n22 * n34 * n43 - n23 * n32 * n44 + n22 * n33 * n44;
    const t12 = n24 * n33 * n41 - n23 * n34 * n41 - n24 * n31 * n43 + n21 * n34 * n43 + n23 * n31 * n44 - n21 * n33 * n44;
    const t13 = n22 * n34 * n41 - n24 * n32 * n41 + n24 * n31 * n42 - n21 * n34 * n42 - n22 * n31 * n44 + n21 * n32 * n44;
    const t14 = n24 * n32 * n41 - n22 * n34 * n41 - n24 * n31 * n42 + n21 * n32 * n42 + n22 * n31 * n43 - n21 * n31 * n43;
    const det = n11 * t11 + n12 * t12 + n13 * t13 + n14 * t14;
    if (!det) return this.identity();
    const detInv = 1 / det;
    e[0] = t11 * detInv; e[1] = t12 * detInv; e[2] = t13 * detInv; e[3] = t14 * detInv;
    e[4] = (n14 * n33 * n42 - n13 * n34 * n42 - n14 * n32 * n43 + n12 * n34 * n43 + n13 * n32 * n44 - n12 * n33 * n44) * detInv;
    e[5] = (n13 * n34 * n41 - n14 * n33 * n41 + n14 * n31 * n43 - n11 * n34 * n43 - n13 * n31 * n44 + n11 * n33 * n44) * detInv;
    e[6] = (n14 * n32 * n41 - n12 * n34 * n41 - n14 * n31 * n42 + n11 * n34 * n42 + n12 * n31 * n44 - n11 * n32 * n44) * detInv;
    e[7] = (n12 * n34 * n41 - n13 * n32 * n41 + n13 * n31 * n42 - n11 * n34 * n42 - n12 * n31 * n43 + n11 * n32 * n43) * detInv;
    /* remaining entries are never consumed in this project */
    return this;
  }
}

export class Euler { constructor(x=0,y=0,z=0){ this.x=x; this.y=y; this.z=z; } }

/* --------------------------- object / camera ----------------------------- */
export class Object3D extends EventDispatcher {
  constructor() {
    super();
    this.position = new Vector3();
    this.quaternion = new Quaternion();
    this.scale = new Vector3(1, 1, 1);
    this.matrixWorld = new Matrix4();
    this.up = new Vector3(0, 1, 0);
  }
  lookAt(target) {
    const f = new Vector3().subVectors(target, this.position);
    if (f.lengthSq() < 1e-12) return this;
    f.normalize();
    const ref = Math.abs(f.y) > 0.995 ? new Vector3(0, 0, 1) : this.up.clone();
    const right = new Vector3().crossVectors(ref, f).normalize();
    const up = new Vector3().crossVectors(f, right).normalize();
    /* camera looks down -Z: basis X=right, Y=up, Z=back */
    this.quaternion.setFromRotationMatrix(new Matrix4().makeBasis(right, up, f.clone().negate()));
    return this;
  }
  updateMatrixWorld() {
    this.matrixWorld.compose(this.position, this.quaternion, this.scale);
    return this;
  }
}

export class Camera extends Object3D {}

export class PerspectiveCamera extends Camera {
  constructor(fov = 55, aspect = 1, near = 0.05, far = 500) {
    super();
    this.fov = fov; this.aspect = aspect; this.near = near; this.far = far;
    this.updateProjectionMatrix();
  }
  updateProjectionMatrix() {
    const near = this.near, far = this.far;
    const top = near * Math.tan(MathUtils.degToRad(0.5 * this.fov));
    const height = 2 * top, width = this.aspect * height;
    const left = -0.5 * width, right = 0.5 * width;
    const e = new Float32Array(16);
    e[0]  = 2 * near / (right - left);
    e[5]  = 2 * near / top / 2 * 0.5 === 0 ? 0 : 2 * near / (top - (-top)); /* stable form below */
    e[5]  = 2 * near / (top - (-top));
    e[8]  = (right + left) / (right - left);
    e[9]  = (top + (-top)) / (top - (-top));
    e[10] = -(far + near) / (far - near);
    e[11] = -1;
    e[14] = -2 * far * near / (far - near);
    this.projectionMatrix = new Matrix4();
    this.projectionMatrix.elements.set(e);
    return this;
  }
}

export class Clock {
  constructor(autoStart = true) { this.autoStart = autoStart; this.elapsedTime = 0; this.oldTime = 0; this.running = false; }
  start() { this.running = true; this.startTime = performance.now() / 1000; this.oldTime = this.startTime; this.elapsedTime = 0; }
  getElapsedTime() { this.getDelta(); return this.elapsedTime; }
  getDelta() {
    let diff = 0;
    if (this.autoStart && !this.running) { this.start(); return 0; }
    if (this.running) {
      const newTime = performance.now() / 1000;
      diff = newTime - this.oldTime;
      this.oldTime = newTime;
      this.elapsedTime += diff;
    }
    return diff;
  }
  stop() { this.running = false; }
}

/* ----------------------------- shader material ---------------------------- */
export class ShaderMaterial {
  constructor(params = {}) {
    this.vertexShader = params.vertexShader || '';
    this.fragmentShader = params.fragmentShader || '';
    this.uniforms = params.uniforms || {};
    this.name = params.name || 'shader';
    /* lazily filled by renderer */
    this._program = null;
  }
}

/* -------------------------------- renderer -------------------------------- */
const UNIFORM_RE = /^[ \t]*uniform[ \t]+(?:highp[ \t]+|mediump[ \t]+|lowp[ \t]+)?(float|int|uint|bool|vec[234]|ivec[234]|bvec[234]|mat[234])[ \t]+(\w+)[ \t]*;/gm;

function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}

export class WebGLRenderer {
  constructor(canvas) {
    this.domElement = canvas;
    const gl = canvas.getContext('webgl2', {
      antialias: false, alpha: false, stencil: false, depth: false,
      premultipliedAlpha: false, preserveDrawingBuffer: true,
      powerPreference: 'high-performance',
    });
    if (!gl) throw new Error('WebGL2 context unavailable.');
    if (!gl.getExtension('EXT_color_buffer_float')) {
      throw new Error('EXT_color_buffer_float unavailable — cannot render HDR.');
    }
    this.gl = gl;
    this._programs = new Map();
    this._targets = [];
    this._initQuad();
    this.setViewportSize(1, 1);
    this.capabilities = { isWebGL2: true, maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE) };
  }

  _initQuad() {
    const gl = this.gl;
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    /* fullscreen triangle, positions already in clip space */
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 0, 3, -1, 0, -1, 3, 0]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 12, 0);
    gl.bindVertexArray(null);
    this._quadVao = vao;
    this._vertSrc = `
      precision highp float;
      layout(location=0) in vec3 position;
      out vec2 vUv;
      void main(){ vUv = position.xy * 0.5 + 0.5; gl_Position = vec4(position.xy, 0.0, 1.0); }`;
  }

  setSize(width, height, pixelRatio = 1) {
    const canvas = this.domElement;
    canvas.width = Math.max(2, Math.floor(width * pixelRatio));
    canvas.height = Math.max(2, Math.floor(height * pixelRatio));
    this.setViewportSize(canvas.width, canvas.height);
  }

  setViewportSize(w, h) { this._width = w; this._height = h; }

  _programFor(material) {
    if (material._program && material._programKey) return material._program;
    const key = material.vertexShader + '\u0000' + material.fragmentShader;
    let entry = this._programs.get(key);
    if (!entry) entry = this._buildProgram(material);
    material._program = entry;
    material._programKey = key;
    return entry;
  }

  _buildProgram(material) {
    const gl = this.gl;
    const vs = this._compile(gl.VERTEX_SHADER, this._vertSrc, material.name + '.vert');
    const fs = this._compile(gl.FRAGMENT_SHADER, material.fragmentShader, material.name + '.frag');
    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      throw new Error(`[${material.name}] program link failed:\n${gl.getProgramInfoLog(prog)}`);
    }
    gl.deleteShader(vs); gl.deleteShader(fs);
    /* discover declared uniforms (unused ones resolve to null and are skipped) */
    const decls = {};
    UNIFORM_RE.lastIndex = 0;
    let m;
    const stripped = stripComments(material.fragmentShader);
    while ((m = UNIFORM_RE.exec(stripped)) !== null) decls[m[2]] = m[1];
    const entry = { prog, uniforms: {} };
    let unit = 0;
    for (const name of Object.keys(decls)) {
      const loc = gl.getUniformLocation(prog, name);
      if (!loc) continue;
      const type = decls[name];
      if (type === 'sampler2D') entry.uniforms[name] = { loc, kind: 'sampler', unit: unit++ };
      else entry.uniforms[name] = { loc, kind: type };
    }
    this._programs.set(key, entry);
    return entry;
  }

  _compile(type, src, label) {
    const gl = this.gl;
    const sh = gl.createShader(type);
    gl.shaderSource(sh, src.trim());
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(sh) || '';
      const numbered = src.split('\n')
        .map((l, i) => String(i + 1).padStart(4) + '| ' + l).join('\n');
      gl.deleteShader(sh);
      throw new Error(`[${label}] compile failed:\n${log}\n${numbered}`);
    }
    return sh;
  }

  _assignUniforms(entry, material) {
    const gl = this.gl;
    const boundSamplers = [];
    for (const [name, u] of Object.entries(material.uniforms)) {
      const meta = entry.uniforms[name];
      if (!meta) continue;
      const v = (u !== null && typeof u === 'object' && 'value' in u) ? u.value : u;
      switch (meta.kind) {
        case 'sampler':
          if (v && v.tex) {
            gl.activeTexture(gl.TEXTURE0 + meta.unit);
            gl.bindTexture(gl.TEXTURE_2D, v.tex);
            gl.uniform1i(meta.loc, meta.unit);
            boundSamplers.push(meta.unit);
          }
          break;
        case 'int': case 'uint': case 'bool':
          gl.uniform1i(meta.loc, v | 0); break;
        case 'float': gl.uniform1f(meta.loc, v); break;
        case 'vec2': gl.uniform2f(meta.loc, v.x, v.y); break;
        case 'vec3': gl.uniform3f(meta.loc, v.x, v.y, v.z); break;
        case 'vec4': gl.uniform4f(meta.loc, v.x, v.y, v.z, v.w); break;
        case 'ivec2': gl.uniform2i(meta.loc, v.x, v.y); break;
        case 'ivec3': gl.uniform3i(meta.loc, v.x, v.y, v.z); break;
        default: break;
      }
    }
    return boundSamplers;
  }

  createRenderTarget(width, height, opts = {}) {
    const gl = this.gl;
    width = Math.max(2, Math.floor(width)); height = Math.max(2, Math.floor(height));
    const internal = opts.halfFloat === false ? gl.RGBA8 : gl.RGBA16F;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, internal, width, height, 0, gl.RGBA,
      opts.halfFloat === false ? gl.UNSIGNED_BYTE : gl.HALF_FLOAT, null);
    const filter = opts.nearest ? gl.NEAREST : gl.LINEAR;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const fbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    const status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    if (status !== gl.FRAMEBUFFER_COMPLETE) throw new Error('Incomplete HDR framebuffer.');
    const rt = { tex, fbo, width, height, type: opts.halfFloat === false ? 'byte' : 'half-float' };
    this._targets.push(rt);
    return rt;
  }

  disposeRenderTarget(rt) {
    if (!rt) return;
    const gl = this.gl;
    gl.deleteFramebuffer(rt.fbo); gl.deleteTexture(rt.tex);
    const i = this._targets.indexOf(rt);
    if (i >= 0) this._targets.splice(i, 1);
  }

  invalidateProgramCache() {
    const gl = this.gl;
    for (const [, entry] of this._programs) gl.deleteProgram(entry.prog);
    this._programs.clear();
  }

  render(material, target = null) {
    const gl = this.gl;
    const entry = this._programFor(material);
    gl.useProgram(entry.prog);
    if (target) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
      gl.viewport(0, 0, target.width, target.height);
    } else {
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.viewport(0, 0, this._width, this._height);
    }
    const samplers = this._assignUniforms(entry, material);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindVertexArray(this._quadVao);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.bindVertexArray(null);
    for (const u of samplers) {
      gl.activeTexture(gl.TEXTURE0 + u);
      gl.bindTexture(gl.TEXTURE_2D, null);
    }
    return entry.prog;
  }

  clearColor(r = 0, g = 0, b = 0, a = 1, target = null) {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, target ? target.fbo : null);
    gl.clearColor(r, g, b, a);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }

  readPixelFloat(rt, x, y) {
    const gl = this.gl;
    const buf = new Float32Array(4);
    gl.bindFramebuffer(gl.FRAMEBUFFER, rt.fbo);
    gl.readPixels(x, y, 1, 1, gl.RGBA, gl.FLOAT, buf);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return buf;
  }

  async captureBlob() {
    const canvas = this.domElement;
    return await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
  }

  dispose() {
    const gl = this.gl;
    for (const rt of this._targets.slice()) this.disposeRenderTarget(rt);
    this.invalidateProgramCache();
    gl.getExtension('WEBGL_lose_context')?.loseContext();
  }
}

export { Vector3 as default };
