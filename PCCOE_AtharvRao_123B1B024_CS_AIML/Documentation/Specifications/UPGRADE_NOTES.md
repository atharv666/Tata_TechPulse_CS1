# GraphMind Frontend Upgrade Notes

## Implemented

The frontend now uses a light, vibrant engineering workspace theme with a white canvas, blue/teal accents, soft depth, improved typography, responsive layout behavior, active navigation states, and clearer status treatments.

The Knowledge Graph screen now renders an interactive 3D WebGL graph using `react-force-graph-3d` and `three`. Nodes are rendered as spheres with color coding for components, interfaces/ports, signals/data types, and requirements. Users can orbit, pan, zoom, drag nodes, hover for labels, click nodes to inspect facts, and click relationships to inspect edges.

The graph workspace includes live node/relationship counts, search filtering, relationship animation, validation-aware link emphasis, a visual legend, and a fact inspector that retains existing review actions and evidence display.

The Ask Architecture screen now includes a graph-grounding callout when the backend returns graph paths. The user can open the Knowledge Graph directly from the answer to continue inspecting the supporting topology. The underlying backend remains authoritative for graph facts, evidence, validation, review, and governance.

## Validation

From `frontend/`:

- `npm run lint`
- `npm test -- --run`
- `npm run build`

All completed successfully during this upgrade. The production build reports only the expected bundle-size advisory from the 3D visualization dependency.

## Running locally

Install dependencies with `npm install`, configure the backend URL using `VITE_API_BASE_URL`, then run `npm run dev` from the `frontend/` directory.

## Experience refinement pass

The landing screen is now a welcome-first workspace. It greets the engineer, explains what GraphMind does, provides direct actions for finding answers and ingesting a document, and places project/document metrics below that orientation layer rather than making metrics the first thing a new user sees.

The home screen now includes a preferred answer-method selector with Graph + source evidence, graph-only, and source-only options, along with a clear path into document ingestion. Secondary governance and operations screens remain available in the navigation but are visually subordinate to the core ask, ingest, and explore workflows.

The graph view has been visually restrained. Sphere size, emissive lighting, link thickness, particle motion, and force settling have all been reduced. Node labels now remain visible by default and include the entity name and type, while the graph canvas uses a quieter professional engineering palette.
