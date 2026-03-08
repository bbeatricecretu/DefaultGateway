import { useRef, useEffect, useCallback } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import './TerminalMap.css';

export default function TerminalMap({ onSelectZone }) {
  const wrapRef = useRef(null);
  const initialized = useRef(false);

  useEffect(() => {
    if (initialized.current || !wrapRef.current) return;
    initialized.current = true;
    const wrap = wrapRef.current;

    // ── Renderer setup ──
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    wrap.appendChild(renderer.domElement);

    const css2d = new CSS2DRenderer();
    css2d.domElement.style.position = 'absolute';
    css2d.domElement.style.top = '0';
    css2d.domElement.style.pointerEvents = 'none';
    wrap.appendChild(css2d.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x050a14);
    scene.fog = new THREE.Fog(0x050a14, 8, 22);

    const camera = new THREE.PerspectiveCamera(45, 2, 0.1, 50);
    camera.position.set(0, 2.8, 3.5);

    const controls = new OrbitControls(camera, css2d.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxPolarAngle = Math.PI / 2.15;
    controls.minDistance = 1;
    controls.maxDistance = 10;

    // Lighting
    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const sun = new THREE.DirectionalLight(0xffffff, 1.1);
    sun.position.set(3, 6, 4);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.near = 0.5;
    sun.shadow.camera.far = 30;
    const sc = sun.shadow.camera;
    sc.left = -6; sc.right = 6; sc.top = 4; sc.bottom = -4;
    scene.add(sun);
    const fill = new THREE.DirectionalLight(0x4488ff, 0.3);
    fill.position.set(-3, 4, -3);
    scene.add(fill);

    // Floor
    let floorMesh;
    const geo = new THREE.PlaneGeometry(1, 1, 1, 1);
    geo.rotateX(-Math.PI / 2);
    const mat = new THREE.MeshStandardMaterial({ color: 0x111111, transparent: true, opacity: 0 });
    floorMesh = new THREE.Mesh(geo, mat);
    floorMesh.receiveShadow = true;
    scene.add(floorMesh);

    const texLoader = new THREE.TextureLoader();
    texLoader.load('/static/floor_plan.png', tex => {
      tex.colorSpace = THREE.SRGBColorSpace;
      const aspect = tex.image.width / tex.image.height;
      floorMesh.scale.set(aspect, 1, 1);
      mat.map = tex;
      mat.opacity = 1;
      mat.needsUpdate = true;
    });

    // Grid helper
    const grid = new THREE.GridHelper(6, 30, 0x1a2a44, 0x0e1525);
    grid.position.y = -0.005;
    scene.add(grid);

    // Coordinate helpers
    let imgAspect = 1381 / 766;
    function imgToWorld(nx, ny) {
      return [(nx - 0.5) * imgAspect, (ny - 0.5)];
    }
    function centroid(pts) {
      const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
      const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
      return imgToWorld(cx, cy);
    }

    const EXTRUDE_H = 0.08;
    const ZONE_Y = 0.001;
    const zoneMeshes = [];

    // Build zones
    function buildZones(zones) {
      zones.forEach(zone => {
        if (!zone.polygons.length) return;
        const pts = zone.polygons[0].points;
        const shape = new THREE.Shape();
        const [sx, sy] = imgToWorld(pts[0][0], pts[0][1]);
        shape.moveTo(sx, sy);
        for (let i = 1; i < pts.length; i++) {
          const [x, y] = imgToWorld(pts[i][0], pts[i][1]);
          shape.lineTo(x, y);
        }
        shape.closePath();

        const geo = new THREE.ExtrudeGeometry(shape, {
          depth: EXTRUDE_H, bevelEnabled: false,
        });
        geo.rotateX(-Math.PI / 2);

        const color = new THREE.Color(zone.color);
        const m = new THREE.MeshStandardMaterial({
          color, transparent: true, opacity: 0.35,
          emissive: color, emissiveIntensity: 0.08,
          roughness: 0.7, metalness: 0.1,
        });
        const mesh = new THREE.Mesh(geo, m);
        mesh.position.y = ZONE_Y;
        mesh.castShadow = true;
        mesh.userData = {
          zoneId: zone.id,
          zoneName: zone.name,
          color: zone.color,
          centroid: (() => { const [cx, cz] = centroid(pts); return [cx, -cz]; })(),
        };

        const edges = new THREE.EdgesGeometry(geo, 8);
        const lm = new THREE.LineBasicMaterial({
          color: new THREE.Color(zone.color).multiplyScalar(1.6),
          transparent: true, opacity: 0.7,
        });
        mesh.add(new THREE.LineSegments(edges, lm));
        scene.add(mesh);
        zoneMeshes.push(mesh);

        // Label
        const labelDiv = document.createElement('div');
        labelDiv.className = 'zone-label';
        labelDiv.textContent = zone.name;
        labelDiv.style.backgroundColor = zone.color + 'cc';
        labelDiv.style.cursor = 'pointer';
        labelDiv.addEventListener('click', () => onSelectZone?.(zone.id));
        const labelObj = new CSS2DObject(labelDiv);
        const [lcx, lcz] = centroid(pts);
        labelObj.position.set(lcx, EXTRUDE_H + 0.06, -lcz);
        scene.add(labelObj);
      });
    }

    // Load zones
    fetch('/static/zones.json')
      .then(r => r.json())
      .then(data => {
        imgAspect = data.image_w / data.image_h;
        floorMesh.scale.set(imgAspect, 1, 1);
        buildZones(data.zones);
        controls.target.set(0, 0, 0);
        controls.update();
      });

    // Raycasting
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();

    function onPointerMove(e) {
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    }

    function onPointerClick() {
      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects(zoneMeshes);
      if (!hits.length) return;
      const { zoneId, zoneName, centroid: [cx, cz] } = hits[0].object.userData;
      controls.target.set(cx, 0, cz);
      camera.position.set(cx, 2.0, cz + 1.8);
      controls.update();
      onSelectZone?.(zoneId);
    }

    wrap.addEventListener('pointermove', onPointerMove);
    wrap.addEventListener('click', onPointerClick);

    // Reset button
    const resetBtn = wrap.querySelector('.btn-reset-cam');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        camera.position.set(0, 2.8, 3.5);
        controls.target.set(0, 0, 0);
        controls.update();
      });
    }

    // Resize
    function resize() {
      const W = wrap.clientWidth;
      const H = wrap.clientHeight;
      renderer.setSize(W, H);
      css2d.setSize(W, H);
      camera.aspect = W / H;
      camera.updateProjectionMatrix();
    }
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    resize();

    // Animate
    let hoveredMesh = null;
    function animate() {
      requestAnimationFrame(animate);
      controls.update();

      raycaster.setFromCamera(mouse, camera);
      const hits = raycaster.intersectObjects(zoneMeshes);
      const newHover = hits.length ? hits[0].object : null;
      if (newHover !== hoveredMesh) {
        if (hoveredMesh) {
          hoveredMesh.material.emissiveIntensity = 0.08;
          hoveredMesh.material.opacity = 0.35;
        }
        hoveredMesh = newHover;
        if (hoveredMesh) {
          hoveredMesh.material.emissiveIntensity = 0.25;
          hoveredMesh.material.opacity = 0.5;
        }
      }

      renderer.render(scene, camera);
      css2d.render(scene, camera);
    }
    animate();

    return () => {
      ro.disconnect();
      wrap.removeEventListener('pointermove', onPointerMove);
      wrap.removeEventListener('click', onPointerClick);
      renderer.dispose();
    };
  }, [onSelectZone]);

  return (
    <div className="map-panel">
      <div className="map-header">
        <span className="map-title">Terminal Floor Plan · 3D</span>
        <span className="map-hint-header">drag to rotate · scroll to zoom · right-drag to pan</span>
        <button className="btn-reset-cam">⟳ Reset View</button>
      </div>
      <div className="map-canvas-wrap" ref={wrapRef}>
        <div className="map-legend" id="map-legend" />
      </div>
    </div>
  );
}
