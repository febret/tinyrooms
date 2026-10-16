import "../../app/vendor/drawflow/drawflow.min.js";
import { escapeHtml } from "./util.js";
import { graphLinks, layoutGraph } from "./graph-model.js";

function nodeHtml(node, addLabel) {
  return `
    <div class="graph-node-head" data-graph-node="${escapeHtml(node.id)}">
      <strong>${escapeHtml(node.title)}</strong>
      <span>${escapeHtml(node.subtitle || "")}</span>
    </div>
    <ol class="graph-ports">
      ${node.ports.map(port => `<li>${escapeHtml(port.label)}</li>`).join("")}
      <li class="graph-port-add">+ ${escapeHtml(addLabel)}</li>
    </ol>
  `;
}

function drawflowData(graph, positions, links) {
  const index = new Map(graph.nodes.map((node, position) => [node.id, String(position + 1)]));
  const data = {};
  graph.nodes.forEach((node, position) => {
    const id = position + 1;
    const point = positions.get(node.id);
    const inputs = { input_1: { connections: [] } };
    if (graph.portInputs) node.ports.forEach((port, portIndex) => { inputs[`input_${portIndex + 2}`] = { connections: [] }; });
    const outputs = {};
    for (let portIndex = 0; portIndex <= node.ports.length; portIndex += 1) outputs[`output_${portIndex + 1}`] = { connections: [] };
    data[id] = {
      id,
      name: "graph-node",
      data: {},
      class: "graph-node",
      html: nodeHtml(node, graph.addLabel),
      typenode: false,
      inputs,
      outputs,
      pos_x: point.x,
      pos_y: point.y,
    };
  });
  for (const link of links) {
    const from = graph.nodes[Number(index.get(link.from)) - 1];
    const to = graph.nodes[Number(index.get(link.to)) - 1];
    const output = `output_${from.ports.findIndex(port => port.id === link.port) + 1}`;
    const input = link.toPort == null ? "input_1" : `input_${to.ports.findIndex(port => port.id === link.toPort) + 2}`;
    data[index.get(link.from)].outputs[output].connections.push({ node: index.get(link.to), output: input });
    data[index.get(link.to)].inputs[input].connections.push({ node: index.get(link.from), input: output });
  }
  return { drawflow: { Home: { data } } };
}

export function createGraphView({ container, onSelectNode, onSelectLink, onChange }) {
  const editor = new globalThis.Drawflow(container);
  editor.curvature = 0.4;
  editor.line_path = 3;
  editor.zoom_min = 0.25;
  editor.start();
  const savedPositions = new Map();
  let graph = { nodes: [] };
  let signature = "";
  let scope = null;
  let stale = true;
  let building = false;
  let pending = null;

  const nodeAt = id => graph.nodes[Number(id) - 1];
  const portAt = (id, outputClass) => nodeAt(id)?.ports[Number(outputClass.slice(7)) - 1]?.id ?? null;
  const inputPortAt = (id, inputClass) => nodeAt(id)?.ports[Number(inputClass.slice(6)) - 2]?.id ?? null;
  const positionsFor = key => {
    if (!savedPositions.has(key)) savedPositions.set(key, new Map());
    return savedPositions.get(key);
  };

  function flush() {
    const changes = pending;
    pending = null;
    const removed = new Set(changes.filter(change => change.type === "remove").map(change => change.node));
    stale = true;
    onChange(changes.filter(change => change.type !== "unlink" || !(removed.has(change.from) || removed.has(change.to))));
  }

  function queue(change) {
    if (building) return;
    if (!pending) {
      pending = [];
      queueMicrotask(flush);
    }
    pending.push(change);
  }

  function linkChange(type, { output_id: outputId, input_id: inputId, output_class: outputClass, input_class: inputClass }) {
    queue({
      type,
      from: nodeAt(outputId)?.id,
      port: portAt(outputId, outputClass),
      to: nodeAt(inputId)?.id,
      toPort: inputPortAt(inputId, inputClass),
    });
  }

  editor.on("connectionCreated", detail => linkChange("link", detail));
  editor.on("connectionRemoved", detail => linkChange("unlink", detail));
  editor.on("nodeRemoved", id => queue({ type: "remove", node: nodeAt(id)?.id }));
  editor.on("nodeMoved", id => {
    const node = editor.drawflow.drawflow.Home.data[id];
    if (node) positionsFor(scope).set(nodeAt(id).id, { x: node.pos_x, y: node.pos_y });
  });
  editor.on("clickEnd", event => {
    const element = event.target.closest?.(".drawflow-node");
    if (!element?.isConnected || event.target.closest(".output,.input,.drawflow-delete")) return;
    container.focus({ preventScroll: true });
    onSelectNode?.(nodeAt(element.id.slice(5))?.id);
  });
  editor.on("connectionSelected", ({ output_id: outputId, output_class: outputClass }) => {
    container.focus({ preventScroll: true });
    onSelectLink?.(nodeAt(outputId)?.id, portAt(outputId, outputClass));
  });

  function build() {
    building = true;
    const links = graphLinks(graph);
    editor.import(drawflowData(graph, layoutGraph(graph, positionsFor(scope)), links), false);
    editor.node_selected = null;
    editor.connection_selected = null;
    for (const link of links.filter(item => item.toPort != null)) {
      const from = graph.nodes.findIndex(node => node.id === link.from);
      const to = graph.nodes.findIndex(node => node.id === link.to);
      const output = graph.nodes[from].ports.findIndex(port => port.id === link.port) + 1;
      const input = graph.nodes[to].ports.findIndex(port => port.id === link.toPort) + 2;
      container.querySelector(`.node_out_node-${from + 1}.node_in_node-${to + 1}.output_${output}.input_${input}`)?.classList.add("is-two-way");
    }
    building = false;
    stale = false;
  }

  function setTransform(x, y, zoom) {
    Object.assign(editor, { canvas_x: x, canvas_y: y, zoom, zoom_last_value: zoom });
    editor.precanvas.style.transform = `translate(${x}px, ${y}px) scale(${zoom})`;
  }

  function fit() {
    const nodes = [...container.querySelectorAll(".drawflow-node")];
    if (!nodes.length || !container.clientWidth) return;
    const left = Math.min(...nodes.map(node => node.offsetLeft));
    const top = Math.min(...nodes.map(node => node.offsetTop));
    const width = Math.max(...nodes.map(node => node.offsetLeft + node.offsetWidth)) - left + 20;
    const height = Math.max(...nodes.map(node => node.offsetTop + node.offsetHeight)) - top;
    const { clientWidth: viewWidth, clientHeight: viewHeight } = container;
    const zoom = Math.max(editor.zoom_min, Math.min(1, (viewWidth - 32) / width, (viewHeight - 32) / height));
    // Drawflow scales the canvas around its centre, so offset the translation by that origin.
    const x = (viewWidth - width * zoom) / 2 - (left - 10) * zoom - (editor.precanvas.clientWidth / 2) * (1 - zoom);
    const y = (viewHeight - height * zoom) / 2 - top * zoom - (editor.precanvas.clientHeight / 2) * (1 - zoom);
    setTransform(x, y, zoom);
  }

  function markActive(activeId) {
    graph.nodes.forEach((node, position) => {
      container.querySelector(`#node-${position + 1}`)?.classList.toggle("is-active", node.id === activeId);
    });
  }

  return {
    fit,
    render({ graph: nextGraph, scope: nextScope = "", activeId = null }) {
      const nextSignature = JSON.stringify(nextGraph);
      if (nextScope !== scope) {
        scope = nextScope;
        stale = true;
        setTransform(0, 0, 1);
      }
      if (nextSignature !== signature) stale = true;
      graph = nextGraph;
      signature = nextSignature;
      if (stale && container.clientWidth > 0) build();
      markActive(activeId);
    },
  };
}
