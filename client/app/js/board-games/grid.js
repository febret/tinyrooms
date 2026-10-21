import * as THREE from "three";
import { shareModelTextures } from "../board-resources.js";
import { createPropEffects } from "../prop-effects.js";
import { boardPositionToSquare, gridConfig, squareToBoardPosition } from "./grid-geometry.js";

const TOP = 0.045;
const X_PER_PERCENT = 0.105;
const Z_PER_PERCENT = 0.085;
const HIGHLIGHT_COLORS = {
  selected: "#ffd66b",
  move: "#74d88b",
  last: "#67a8e8",
};

export { boardPositionToSquare, squareToBoardPosition };

/** Create the grid renderer used by chess and other square-board games. */
export function createGridRenderer(context) {
  const group = new THREE.Group();
  const piecesGroup = new THREE.Group();
  const highlightsGroup = new THREE.Group();
  group.add(highlightsGroup, piecesGroup);
  context.root.add(group);
  const highlightGeometry = new THREE.PlaneGeometry(1, 1);
  const highlightMaterials = new Map(
    Object.entries(HIGHLIGHT_COLORS).map(([name, color]) => [
      name,
      new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: 0.5,
        depthWrite: false,
        side: THREE.DoubleSide,
      }),
    ]),
  );
  const modelCache = new Map();
  const records = new Map();
  let game = null;
  let state = null;
  let grid = null;
  let roomDark = false;
  let reducedMotion = false;
  let selectedSquare = "";
  let boardKey = "";
  let boardMesh = null;
  let boardTexture = null;

  function positionForSquare(square) {
    const percent = squareToBoardPosition(grid, square);
    if (!percent) return null;
    return new THREE.Vector3(
      (percent[0] - 50) * X_PER_PERCENT,
      TOP + 0.012,
      (percent[1] - 50) * Z_PER_PERCENT,
    );
  }

  function squareAt(position) {
    return boardPositionToSquare(grid, position);
  }

  function cellWidthPercent() {
    return grid ? grid.size[0] / grid.columns : 0;
  }

  function cellDepthPercent() {
    return grid ? grid.size[1] / grid.rows : 0;
  }

  function cellWorldSize() {
    return Math.min(
      (cellWidthPercent() * X_PER_PERCENT) || 0,
      (cellDepthPercent() * Z_PER_PERCENT) || 0,
    );
  }

  function clearHighlights() {
    for (const child of [...highlightsGroup.children]) highlightsGroup.remove(child);
  }

  function addHighlight(square, kind) {
    const position = positionForSquare(square);
    if (!position) return;
    const mesh = new THREE.Mesh(highlightGeometry, highlightMaterials.get(kind) || highlightMaterials.move);
    mesh.rotation.x = -Math.PI / 2;
    mesh.scale.set(cellWidthPercent() * X_PER_PERCENT * 0.88, cellDepthPercent() * Z_PER_PERCENT * 0.88, 1);
    mesh.position.copy(position);
    mesh.position.y = TOP + 0.004;
    highlightsGroup.add(mesh);
  }

  function applyHighlights() {
    clearHighlights();
    if (!state || !grid || roomDark) return;
    if (state.last_move?.from) addHighlight(state.last_move.from, "last");
    if (state.last_move?.to) addHighlight(state.last_move.to, "last");
    const targets = selectedSquare ? state.moves?.[selectedSquare] || [] : [];
    if (selectedSquare) addHighlight(selectedSquare, "selected");
    for (const square of targets) addHighlight(square, "move");
    if (selectedSquare && targets.length === 0) selectedSquare = "";
    context.invalidate();
  }

  function disposeObject(root) {
    if (!root) return;
    const geometries = new Set();
    const materials = new Set();
    root.traverse(node => {
      if (node.geometry) geometries.add(node.geometry);
      if (node.material) {
        for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
          materials.add(material);
        }
      }
    });
    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
  }

  function fallbackPiece(code) {
    const color = code.startsWith("b") ? "#26262a" : "#f2ead4";
    const material = new THREE.MeshStandardMaterial({ color, roughness: 0.62, metalness: 0.05 });
    const kind = code[1] || "P";
    const root = new THREE.Group();
    const base = new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.38, 0.12, 16), material);
    base.position.y = 0.06;
    root.add(base);
    let body;
    if (kind === "N") {
      body = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.7, 0.34), material);
      body.position.y = 0.47;
      body.rotation.z = 0.16;
    } else if (kind === "B") {
      body = new THREE.Mesh(new THREE.ConeGeometry(0.26, 0.9, 16), material);
      body.position.y = 0.57;
    } else if (kind === "R") {
      body = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.34, 0.78, 16), material);
      body.position.y = 0.51;
    } else if (kind === "Q") {
      body = new THREE.Mesh(new THREE.ConeGeometry(0.34, 1.05, 16), material);
      body.position.y = 0.64;
    } else if (kind === "K") {
      body = new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.34, 1.0, 16), material);
      body.position.y = 0.62;
      const crown = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.12, 0.32), material);
      crown.position.y = 1.18;
      root.add(crown);
    } else {
      body = new THREE.Mesh(new THREE.SphereGeometry(0.3, 16, 12), material);
      body.position.y = 0.42;
    }
    root.add(body);
    root.traverse(node => {
      if (node.isMesh) node.castShadow = node.receiveShadow = true;
    });
    return root;
  }

  function normalizeModel(model) {
    const box = new THREE.Box3().setFromObject(model);
    const size = new THREE.Vector3();
    box.getSize(size);
    const height = size.y || 1;
    const target = Math.max(0.3, cellWorldSize() * 1.85);
    const scale = target / height;
    model.scale.multiplyScalar(scale);
    box.setFromObject(model);
    const center = new THREE.Vector3();
    box.getCenter(center);
    model.position.x -= center.x;
    model.position.z -= center.z;
    model.position.y -= box.min.y;
  }

  function loadModel(url) {
    if (!url) return Promise.resolve(null);
    const cached = modelCache.get(url);
    if (cached) return cached;
    const pending = new Promise(resolve => {
      context.loader.load(
        url,
        gltf => {
          gltf.scene.traverse(node => {
            if (node.isMesh) node.castShadow = node.receiveShadow = true;
          });
          shareModelTextures(gltf.scene, url);
          resolve(gltf);
        },
        undefined,
        () => resolve(null),
      );
    });
    modelCache.set(url, pending);
    return pending;
  }

  function refreshRecordEffect(record) {
    const hazard = record.hazard || "";
    const model = record.loadedModel || record.fallback;
    const key = `${hazard}|${record.loadedModel ? "model" : "fallback"}|${reducedMotion ? "reduced" : "full"}`;
    if (record.effectKey === key) return;
    record.effectController?.dispose();
    record.effectController = null;
    record.effectKey = key;
    if (!hazard || !model || reducedMotion || !game?.effects?.[hazard]) return;
    const bounds = new THREE.Box3().setFromObject(record.group);
    record.effectController = createPropEffects({
      group: record.group,
      visual: record.group,
      model,
      bounds,
      effectSets: game.effects,
      activeEffect: hazard,
      reducedMotion,
      textureLoader: context.textureLoader,
      pixelScale: context.pixelScale,
      wake: context.invalidate,
    });
  }

  function removeRecord(id) {
    const record = records.get(id);
    if (!record) return;
    record.disposed = true;
    record.effectController?.dispose();
    record.effectController = null;
    record.group.removeFromParent();
    disposeObject(record.fallback);
    records.delete(id);
  }

  function createRecord(piece) {
    const info = game?.models?.[piece.code] || null;
    const record = {
      id: piece.id,
      code: piece.code,
      group: new THREE.Group(),
      fallback: fallbackPiece(piece.code),
      target: new THREE.Vector3(),
      disposed: false,
      loadedModel: null,
      hazard: "",
      effectController: null,
      effectKey: "",
    };
    record.group.add(record.fallback);
    piecesGroup.add(record.group);
    records.set(piece.id, record);
    if (info?.modelUrl) {
      const targetCode = piece.code;
      loadModel(info.modelUrl).then(gltf => {
        if (!gltf || record.disposed || record.code !== targetCode) return;
        const model = gltf.scene.clone(true);
        normalizeModel(model);
        model.scale.multiplyScalar(Number(info.scale) || 1);
        if (record.fallback) {
          record.group.remove(record.fallback);
          disposeObject(record.fallback);
          record.fallback = null;
        }
        record.loadedModel = model;
        record.group.add(model);
        refreshRecordEffect(record);
        context.invalidate();
        context.invalidateShadows?.();
      });
    }
    return record;
  }

  function syncPieces() {
    const seen = new Set();
    let moved = false;
    for (const piece of state?.pieces || []) {
      seen.add(piece.id);
      let record = records.get(piece.id);
      if (record && record.code !== piece.code) {
        removeRecord(piece.id);
        record = null;
        moved = true;
      }
      if (!record) {
        record = createRecord(piece);
        moved = true;
      }
      const position = positionForSquare(piece.square);
      if (!position) continue;
      if (record.target.lengthSq() === 0 || record.group.position.lengthSq() === 0) {
        record.group.position.copy(position);
        moved = true;
      }
      if (!record.target.equals(position)) moved = true;
      record.target.copy(position);
      record.group.rotation.y = piece.code.startsWith("b") ? Math.PI : 0;
      record.hazard = state?.hazards?.[piece.square] || "";
      refreshRecordEffect(record);
    }
    for (const id of [...records.keys()]) {
      if (!seen.has(id)) {
        removeRecord(id);
        moved = true;
      }
    }
    if (moved) context.invalidateShadows?.();
  }

  function createBoardTexture() {
    const canvas = document.createElement("canvas");
    const columns = grid.columns;
    const rows = grid.rows;
    const cellPx = Math.max(64, Math.min(160, Math.floor(1024 / Math.max(columns, rows))));
    canvas.width = columns * cellPx;
    canvas.height = rows * cellPx;
    const painter = canvas.getContext("2d");
    if (!painter) return new THREE.CanvasTexture(canvas);
    const light = typeof game?.config?.light === "string" ? game.config.light : "#efdfbd";
    const dark = typeof game?.config?.dark === "string" ? game.config.dark : "#5b3b28";
    painter.fillStyle = light;
    painter.fillRect(0, 0, canvas.width, canvas.height);
    painter.fillStyle = dark;
    for (let row = 0; row < rows; row += 1) {
      for (let column = 0; column < columns; column += 1) {
        if ((row + column) % 2 === 0) continue;
        painter.fillRect(column * cellPx, row * cellPx, cellPx, cellPx);
      }
    }
    const border = Math.max(2, Math.round(cellPx * 0.045));
    painter.strokeStyle = "#2a1b14";
    painter.lineWidth = border;
    painter.strokeRect(border / 2, border / 2, canvas.width - border, canvas.height - border);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = 8;
    const grainUrl = game?.assets?.grain || game?.assets?.board;
    if (grainUrl) {
      context.textureLoader.load(grainUrl, grain => {
        if (boardTexture !== texture || !boardMesh || !grain.image) return;
        painter.save();
        painter.globalAlpha = 0.16;
        painter.globalCompositeOperation = "multiply";
        try {
          painter.drawImage(grain.image, 0, 0, canvas.width, canvas.height);
        } catch {
          // The procedural checkerboard is complete without the optional grain.
        }
        painter.restore();
        texture.needsUpdate = true;
        context.invalidate();
      }, undefined, () => {});
    }
    return texture;
  }

  function rebuildBoard() {
    if (boardMesh) {
      boardMesh.removeFromParent();
      boardMesh.geometry.dispose();
      boardMesh.material.dispose();
      boardMesh = null;
    }
    if (boardTexture) {
      boardTexture.dispose();
      boardTexture = null;
    }
    if (!grid) return;
    const width = grid.size[0] * X_PER_PERCENT;
    const depth = grid.size[1] * Z_PER_PERCENT;
    if (!width || !depth) return;
    boardTexture = createBoardTexture();
    const material = new THREE.MeshStandardMaterial({ map: boardTexture, roughness: 0.9 });
    boardMesh = new THREE.Mesh(new THREE.PlaneGeometry(width, depth), material);
    boardMesh.rotation.x = -Math.PI / 2;
    boardMesh.receiveShadow = true;
    const x = grid.origin[0] + grid.size[0] / 2;
    const y = grid.origin[1] + grid.size[1] / 2;
    boardMesh.position.set((x - 50) * X_PER_PERCENT, TOP + 0.002, (y - 50) * Z_PER_PERCENT);
    group.add(boardMesh);
  }

  function resetSelectionIfInvalid() {
    if (!selectedSquare || !state?.moves?.[selectedSquare]) selectedSquare = "";
  }

  function sync(next) {
    game = next.game || null;
    state = next.state || null;
    roomDark = Boolean(next.dark);
    reducedMotion = Boolean(next.reducedMotion);
    grid = gridConfig(game?.config);
    const active = Boolean(game && grid && !roomDark);
    group.visible = active;
    if (!active) {
      clearHighlights();
      return;
    }
    resetSelectionIfInvalid();
    const key = [
      game.assets?.grain || game.assets?.board || "",
      `${grid.columns}x${grid.rows}`,
      grid.origin.join(","),
      grid.size.join(","),
      game.config?.light || "",
      game.config?.dark || "",
    ].join("|");
    if (!boardMesh || boardKey !== key) {
      boardKey = key;
      rebuildBoard();
    }
    syncPieces();
    applyHighlights();
    context.invalidate();
  }

  function pointerUp(clientX, clientY) {
    if (!grid || !state || roomDark || !group.visible) return false;
    const point = context.screenToBoardPosition?.(clientX, clientY);
    if (!point) return false;
    const square = squareAt(point.position);
    if (!square) return false;
    const fromSquare = selectedSquare;
    const legal = fromSquare ? state.moves?.[fromSquare] || [] : [];
    if (fromSquare && legal.includes(square)) {
      const piece = state.pieces.find(item => item.square === fromSquare);
      const targetRank = Number(square.slice(1));
      const promotion = piece?.code?.[1] === "P" && (targetRank === 1 || targetRank === grid.rows) ? "q" : "";
      selectedSquare = "";
      applyHighlights();
      context.action?.(`move:${fromSquare}${square}${promotion}`);
      return true;
    }
    if ((state.moves?.[square] || []).length) {
      selectedSquare = square;
      applyHighlights();
      return true;
    }
    selectedSquare = "";
    applyHighlights();
    return true;
  }

  function advance(delta) {
    if (!group.visible) return;
    const alpha = reducedMotion ? 1 : 1 - Math.exp(-delta * 14);
    for (const record of records.values()) {
      record.effectController?.update(delta);
      if (!record.target) continue;
      if (reducedMotion) record.group.position.copy(record.target);
      else record.group.position.lerp(record.target, alpha);
    }
  }

  function isAnimating() {
    if (!group.visible) return false;
    for (const record of records.values()) {
      if (record.target && record.group.position.distanceToSquared(record.target) > 1e-6) return true;
      if (record.effectController?.isAnimating()) return true;
    }
    return false;
  }

  function itemCount() {
    return records.size;
  }

  function clear() {
    clearHighlights();
    for (const id of [...records.keys()]) removeRecord(id);
    if (boardMesh) {
      boardMesh.removeFromParent();
      boardMesh.geometry.dispose();
      boardMesh.material.dispose();
      boardMesh = null;
    }
    if (boardTexture) {
      boardTexture.dispose();
      boardTexture = null;
    }
    boardKey = "";
    selectedSquare = "";
    game = null;
    state = null;
    grid = null;
    roomDark = false;
    group.visible = false;
  }

  function dispose() {
    clear();
    for (const material of highlightMaterials.values()) material.dispose();
    highlightGeometry.dispose();
    group.removeFromParent();
  }

  return {
    sync,
    pointerUp,
    advance,
    isAnimating,
    itemCount,
    clear,
    dispose,
  };
}
