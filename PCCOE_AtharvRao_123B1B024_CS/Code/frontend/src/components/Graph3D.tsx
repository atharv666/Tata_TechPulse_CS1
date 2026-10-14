import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D, { type ForceGraphMethods } from "react-force-graph-3d";
import * as THREE from "three";
import { TONE_HEX, tone, toneLabel } from "../lib/graphView";
import type { Entity, Relationship } from "../types/api";

type GraphNode = Entity & { x?: number; y?: number; z?: number };
type GraphLink = Relationship & { source: string | GraphNode; target: string | GraphNode };

/** Sphere size encodes the entity type family; colour encodes the review state (and is also text). */
function sizeFor(type: string): number {
  const name = type.toLowerCase();
  if (name.includes("interface")) return 3.6;
  if (name.includes("signal") || name.includes("data")) return 2.8;
  return 4.2;
}

function labelSprite(node: GraphNode) {
  const canvas = document.createElement("canvas");
  canvas.width = 640;
  canvas.height = 120;
  const context = canvas.getContext("2d");
  if (!context) return new THREE.Group();
  context.textAlign = "center";
  context.font = "600 28px Inter, Arial, sans-serif";
  context.fillStyle = "#233b55";
  context.fillText(node.canonical_name.length > 28 ? `${node.canonical_name.slice(0, 27)}…` : node.canonical_name, 320, 32);
  context.font = "500 19px Inter, Arial, sans-serif";
  context.fillStyle = "#6f8195";
  context.fillText(`${node.entity_type} · ${node.validation_state}`, 320, 62);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, depthWrite: false }));
  sprite.scale.set(66, 12.4, 1);
  sprite.position.set(0, -10, 0);
  return sprite;
}

interface Props {
  nodes: Entity[];
  relationships: Relationship[];
  onSelectEntity: (id: string) => void;
  onSelectRelationship: (id: string) => void;
}

export function Graph3D({ nodes, relationships, onSelectEntity, onSelectRelationship }: Props) {
  // The canvas must follow its card, not the browser window.
  const wrap = useRef<HTMLDivElement>(null);
  const graph = useRef<ForceGraphMethods<GraphNode, GraphLink> | undefined>(undefined);
  const [size, setSize] = useState({ width: 800, height: 610 });
  useEffect(() => {
    const element = wrap.current;
    if (!element) return;
    const measure = () => setSize({ width: Math.max(280, Math.floor(element.clientWidth)), height: Math.max(320, Math.floor(element.clientHeight)) });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const fit = () => graph.current?.zoomToFit(600, 12);
  const data = useMemo(() => {
    const ids = new Set(nodes.map((node) => node.id));
    return {
      nodes: nodes.map((node) => ({ ...node })),
      links: relationships
        .filter((edge) => ids.has(edge.source_entity_id) && ids.has(edge.target_entity_id))
        .map((edge) => ({ ...edge, source: edge.source_entity_id, target: edge.target_entity_id })) as GraphLink[],
    };
  }, [nodes, relationships]);

  // Re-fit when the data or the canvas size changes (the layout settles a moment later).
  useEffect(() => {
    const timers = [1200, 3500].map((delay) => window.setTimeout(fit, delay));
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [data, size.width, size.height]);

  return (
    <div className="graph-3d-wrap" ref={wrap}>
      <ForceGraph3D
        ref={graph}
        onEngineStop={fit}
        width={size.width}
        height={size.height}
        graphData={data}
        backgroundColor="#f7fbff"
        nodeLabel={(node: GraphNode) => `${node.canonical_name} · ${node.entity_type} · ${toneLabel(tone(node))}`}
        nodeRelSize={3.2}
        linkColor={(link: GraphLink) => TONE_HEX[tone(link)] + "99"}
        linkHoverPrecision={8}
        linkWidth={(link: GraphLink) => (link.validation_state.startsWith("HUMAN") ? 1.8 : 0.9)}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkLabel={(link: GraphLink) => `${link.relationship_type} · ${toneLabel(tone(link))}`}
        nodeThreeObject={(node: GraphNode) => {
          const color = TONE_HEX[tone(node)];
          const group = new THREE.Group();
          const geometry = new THREE.SphereGeometry(sizeFor(node.entity_type), 18, 18);
          const material = new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0.05, emissive: color, emissiveIntensity: 0.04 });
          group.add(new THREE.Mesh(geometry, material));
          group.add(labelSprite(node));
          return group;
        }}
        nodeThreeObjectExtend={false}
        onNodeClick={(node: GraphNode) => onSelectEntity(node.id)}
        onLinkClick={(link: GraphLink) => onSelectRelationship(link.id)}
        showNavInfo={false}
        enableNodeDrag
        enableNavigationControls
        cooldownTicks={80}
        d3AlphaDecay={0.08}
        d3VelocityDecay={0.5}
      />
    </div>
  );
}
