import { useMemo } from "react";
import ForceGraph3D from "react-force-graph-3d";
import * as THREE from "three";
import type { Entity, Relationship } from "../types/api";

type GraphNode = Entity & { x?: number; y?: number; z?: number };
type GraphLink = Relationship & { source: string | GraphNode; target: string | GraphNode };

function colorFor(type: string) {
  const normalized = type.toLowerCase();
  if (normalized.includes("interface") || normalized.includes("port")) return "#4667a8";
  if (normalized.includes("signal") || normalized.includes("datatype")) return "#bd7a3b";
  if (normalized.includes("requirement")) return "#a95772";
  return "#167f78";
}

function labelSprite(node: GraphNode) {
  const canvas = document.createElement("canvas");
  canvas.width = 640;
  canvas.height = 96;
  const context = canvas.getContext("2d");
  if (!context) return new THREE.Group();
  context.font = "600 28px Inter, Arial, sans-serif";
  context.fillStyle = "#233b55";
  context.textAlign = "center";
  context.fillText(node.canonical_name.length > 28 ? `${node.canonical_name.slice(0, 27)}…` : node.canonical_name, 320, 34);
  context.font = "500 19px Inter, Arial, sans-serif";
  context.fillStyle = "#6f8195";
  context.fillText(node.entity_type, 320, 68);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, depthWrite: false }));
  sprite.scale.set(42, 6.3, 1);
  sprite.position.set(0, -9, 0);
  return sprite;
}

export function Graph3D({ nodes, relationships, onSelect }: { nodes: Entity[]; relationships: Relationship[]; onSelect: (item: Entity | Relationship) => void }) {
  const nodeById = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const data = useMemo(() => ({ nodes: nodes.map((node) => ({ ...node })), links: relationships.filter((edge) => nodeById.has(edge.source_entity_id) && nodeById.has(edge.target_entity_id)).map((edge) => ({ ...edge, source: edge.source_entity_id, target: edge.target_entity_id })) as GraphLink[] }), [nodes, relationships, nodeById]);

  return <div className="graph-3d-wrap"><ForceGraph3D graphData={data} backgroundColor="#f7fbff" nodeLabel={(node: GraphNode) => `${node.canonical_name} · ${node.entity_type}`} nodeColor={(node: GraphNode) => colorFor(node.entity_type)} nodeRelSize={3.2} nodeVal={(node: GraphNode) => 1 + Math.min(1.8, (node.confidence ?? 0.5) * 1.8)} linkColor={() => "rgba(104, 126, 151, 0.34)"} linkWidth={(link: GraphLink) => link.validation_state === "HUMAN_VERIFIED" ? 1.8 : 0.9} linkDirectionalParticles={0} linkLabel={(link: GraphLink) => link.relationship_type} nodeThreeObject={(node: GraphNode) => { const group = new THREE.Group(); const geometry = new THREE.SphereGeometry(3.3 + (node.confidence ?? 0.5) * 1.4, 18, 18); const material = new THREE.MeshStandardMaterial({ color: colorFor(node.entity_type), roughness: 0.62, metalness: 0.05, emissive: colorFor(node.entity_type), emissiveIntensity: 0.02 }); group.add(new THREE.Mesh(geometry, material)); group.add(labelSprite(node)); return group; }} nodeThreeObjectExtend={false} onNodeClick={(node: GraphNode) => onSelect(nodeById.get(node.id) ?? node)} onLinkClick={(link: GraphLink) => { const edge = relationships.find((item) => item.id === link.id); if (edge) onSelect(edge); }} showNavInfo={false} enableNodeDrag enableNavigationControls cooldownTicks={80} d3AlphaDecay={0.08} d3VelocityDecay={0.5} />
  </div>;
}
