# Course Production Task List

Full outstanding task list for "From RAG Prototype to Production: AI Data Architecture on AWS".

---

## Phase 0: Infrastructure Testing and Commit

- [x] Push all current work to github.com/kandmgawron/dataforai (PR #1: phase-0-seed-scripts-and-data)
- [x] Scrub docs/ from git history (internal files moved to .kiro/docs)
- [x] Consolidate to single region (eu-west-1), make region overridable
- [x] Switch ElastiCache from Redis to Valkey
- [x] Fix dynamic AZs in CloudFormation (no hardcoded eu-west-2a/b)
- [x] Fix S3 bucket naming (include region for uniqueness)
- [x] Deploy meridian-base in eu-west-1
- [x] Deploy meridian-vectors in eu-west-1 (now folded into meridian-base)
- [x] Run seed scripts with --limit 10 to verify connectivity (products, customers, reviews, conversations, policies)
- [x] Run full make seed-data and confirm counts: 22.5k products, 5k customers, 200k reviews, 50k conversations, 40 policies
- [ ] Tear down (make destroy-all)

---

## Phase 0B: Frontends (Ridge Assist + Ridge Insight)

Both frontends are static HTML/JS hosted from S3/CloudFront. They start "dumb" (basic SQL keyword search) and progressively gain AI features as the course adds datastores.

### Ridge Assist (customer-facing shop)
- [ ] Build static frontend: product catalogue browse with categories
- [ ] Basic search bar (SQL LIKE query via API Gateway + Lambda)
- [ ] Chat widget (submits questions but no AI response; questions queue for Ridge Insight staff to answer)
- [ ] Product detail pages (pulled from Aurora)
- [ ] Minimal styling, dark theme consistent with course slides

### Ridge Insight (internal CRM/staff tool)
- [ ] Build static frontend: customer lookup by ID/name/email
- [ ] Customer detail view: purchase history, conversation history
- [ ] Queued customer questions from Ridge Assist chat (staff answers manually)
- [ ] Policy document viewer (browse policies from S3)
- [ ] Basic keyword search across products, customers, policies
- [ ] No AI components initially; same SQL-backed search

### API Layer
- [ ] API Gateway + Lambda functions for search, customer lookup, conversations, policies
- [ ] CloudFormation for API layer (part of meridian-base or a thin meridian-api stack)
- [ ] Wire frontends to API endpoints

### Progressive Enhancement (tied to course modules)
The same frontends gain capabilities as each module is completed:
- Module 3: Vector search replaces SQL LIKE for product search
- Module 5: RAG-powered answers appear in Ridge Assist chat
- Module 7: Hybrid search (BM25 + vector) replaces pure vector
- Module 8-9: Conversation memory persists across sessions
- Module 11: Personalised results based on customer history
- Module 14: Agents for Amazon Bedrock handle structured queries (stock, pricing)
- Module 16: Semantic caching reduces response latency

### Deployment
- [ ] Add S3 static hosting + CloudFront to meridian-base.yaml (or a meridian-web stack)
- [ ] make deploy-web target
- [ ] Frontends deployed as part of initial stack setup

---

## Phase 1: Visual Standards

- [ ] Decide architecture diagram tool (Excalidraw, draw.io, or other)
- [ ] Define colour palette tied to dark-theme slide deck
- [ ] Define iconography set (AWS Architecture Icons 2024)
- [ ] Create "Meridian current stack" architecture diagram (reused throughout course)
- [ ] Create "Meridian Ridge architecture" diagram (the "after" state)
- [ ] Create slide deck template (HTML, dark theme) for reuse across all modules

---

## Phase 2: Module 1 — Meet Meridian (Section 1)

### Video 1: Meet Meridian — DONE (recorded)

### Video 2: Environment Setup
- [ ] Build setup video slide deck (HTML, dark theme)
- [ ] Write speaker notes for setup video
- [ ] Build 01-setup-check.ipynb (verification notebook: Bedrock, Aurora, OpenSearch, DynamoDB, S3 connectivity checks)
- [ ] Record Video 2

### Video 3: Embeddings on AWS (Module 2)
- [ ] Build slide deck for embeddings module
- [ ] Write speaker notes
- [ ] Build notebook: 02-embeddings.ipynb (Titan Embed v2 calls, Cohere comparison, dimension exploration, cost calculation)
- [ ] Record Video 3

### Video 4: Choosing a Vector Store on AWS (Module 3)
- [ ] Build slide deck (decision framework: OpenSearch Serverless vs pgvector vs S3 Vectors vs Bedrock KB vs Kendra)
- [ ] Write speaker notes
- [ ] Build notebook: 03-vector-store-comparison.ipynb (same query against pgvector AND OpenSearch, side-by-side results)
- [ ] Confirm OpenSearch is deployed in meridian-base and working before recording
- [ ] Record Video 4

### Video 5: Vector Database Architecture (Module 4)
- [ ] Build slide deck (sizing, sharding, replication, capacity planning for 22.5k SKUs)
- [ ] Write speaker notes
- [ ] Record Video 5 (slides + demo only, no notebook)

### Video 6: Implementing RAG with Bedrock (Module 5)
- [ ] Build slide deck
- [ ] Write speaker notes
- [ ] Build notebook: 05-rag-implementation.ipynb (end-to-end: retrieve, prompt, call Bedrock, return answer)
- [ ] Record Video 6

### Video 7: RAG Anti-patterns (Module 6)
- [ ] Build slide deck (lost-in-the-middle, over-stuffing, hallucination on empty retrieval, prompt injection)
- [ ] Write speaker notes
- [ ] Build notebook: 06-rag-antipatterns.ipynb (demonstrate each anti-pattern, show instrumentation)
- [ ] Record Video 7

### Video 8: Hybrid Search (Module 7)
- [ ] Build slide deck (BM25 + vector, score combination, weighting)
- [ ] Write speaker notes
- [ ] Build notebook: 07-hybrid-search.ipynb (OpenSearch hybrid query, weight comparison)
- [ ] Record Video 8

---

## Phase 3: Section 2 — Making It Smart

### Infrastructure: meridian-knowledge.yaml
- [ ] Build meridian-knowledge.yaml (Neptune, Bedrock Knowledge Base)
- [ ] Deploy and test meridian-knowledge stack
- [ ] Tear down after confirming

### Infrastructure: meridian-agents.yaml
- [ ] Build meridian-agents.yaml (Agents for Amazon Bedrock; optional AgentCore for learners who want custom agents)
- [ ] Deploy and test agents stack
- [ ] Tear down after confirming

### Video 9: Context Memory (Module 8)
- [ ] Build slide deck (session vs long-term state, DynamoDB + ElastiCache design)
- [ ] Write speaker notes
- [ ] Build notebook: 08-context-memory.ipynb
- [ ] Record Video 9

### Video 10: Building Ridge's Production Memory System (Module 9)
- [ ] Build slide deck (capture, extract, store, retrieve lifecycle)
- [ ] Write speaker notes
- [ ] Build notebook: 09-memory-system.ipynb
- [ ] Record Video 10

### Video 11: Retrieval-Augmented Memory (Module 10)
- [ ] Build slide deck (summarise past conversations, recall relevant history)
- [ ] Write speaker notes
- [ ] Build notebook: 10-retrieval-augmented-memory.ipynb
- [ ] Record Video 11

### Video 12: Personalisation via Retrieval (Module 11)
- [ ] Build slide deck (user embeddings, bias retrieval, cold-start handling)
- [ ] Write speaker notes
- [ ] Build notebook: 11-personalisation.ipynb
- [ ] Record Video 12

### Video 13: Query Expansion and Transformation (Module 12)
- [ ] Build slide deck (sub-query decomposition, ambiguity, measuring expansion)
- [ ] Write speaker notes
- [ ] Record Video 13 (slides + demo, no notebook)

### Video 14: Metadata Filtering (Module 13)
- [ ] Build slide deck (pre-filter vs post-filter, multi-level, dynamic metadata)
- [ ] Write speaker notes
- [ ] Build notebook: 13-metadata-filtering.ipynb
- [ ] Record Video 14

### Video 15: Structured RAG with Bedrock Agents (Module 14)
- [ ] Build slide deck (Agents querying Aurora for live stock, pricing, order status)
- [ ] Write speaker notes
- [ ] Build notebook: 14-structured-rag-agents.ipynb
- [ ] Record Video 15

### Video 16: Knowledge Graphs with Neptune (Module 15)
- [ ] Build slide deck (graph relationships, combining graph + vector retrieval)
- [ ] Write speaker notes
- [ ] Build notebook: 15-knowledge-graphs.ipynb
- [ ] Record Video 16

---

## Phase 4: Section 3 — Making It Fast and Cheap

### Video 17: Semantic Caching (Module 16)
- [ ] Build slide deck (caching by meaning, similarity thresholds, TTL, bypass)
- [ ] Write speaker notes
- [ ] Build notebook: 16-semantic-caching.ipynb
- [ ] Record Video 17

### Video 18: Multi-level Caching (Module 17)
- [ ] Build slide deck (L1/L2/L3, Ridge Assist vs Ridge Insight tuning)
- [ ] Write speaker notes
- [ ] Build notebook: 17-multilevel-caching.ipynb
- [ ] Record Video 18

### Video 19: Summarisation and Context Compression (Module 18)
- [ ] Build slide deck (extractive vs abstractive, when compression hurts)
- [ ] Write speaker notes
- [ ] Record Video 19 (slides + demo, no notebook)

### Video 20: Managing Embeddings at Scale (Module 19)
- [ ] Build slide deck (batch generation, incremental updates, version upgrades, Lambda + Step Functions)
- [ ] Write speaker notes
- [ ] Build notebook: 19-embeddings-at-scale.ipynb
- [ ] Record Video 20

### Video 21: Seasonal Patterns with Timestream (Module 20)
- [ ] Build slide deck (time-series for seasonal personalisation + operational metrics)
- [ ] Write speaker notes
- [ ] Build notebook: 20-timestream-seasonal.ipynb
- [ ] Record Video 21

### Video 22: Cost Optimisation Across the Stack (Module 21)
- [ ] Build slide deck (Bedrock pricing, vector store economics, cache ROI, cost model)
- [ ] Write speaker notes
- [ ] Build notebook: 21-cost-optimisation.ipynb (full cost model spreadsheet/calculation)
- [ ] Record Video 22

---

## Phase 5: Section 4 — Making It Reliable

### Infrastructure: meridian-ops.yaml
- [ ] Build meridian-ops.yaml (Timestream, Step Functions, CloudWatch dashboards)
- [ ] Deploy and test meridian-ops stack
- [ ] Tear down after confirming

### Video 23: Observability for Retrieval Systems (Module 22)
- [ ] Build slide deck (CloudWatch metrics, Bedrock invocation logs, custom metrics, alerting)
- [ ] Write speaker notes
- [ ] Build notebook: 22-observability.ipynb
- [ ] Record Video 23

### Video 24: Measuring Retrieval Quality (Module 23)
- [ ] Build evaluation harness (100-200 test queries with expected results)
- [ ] Build slide deck (offline eval, online eval, precision@K, recall)
- [ ] Write speaker notes
- [ ] Build notebook: 23-retrieval-quality.ipynb
- [ ] Record Video 24

### Video 25: Multi-index Strategies (Module 24)
- [ ] Build slide deck (separate indexes per data type, coordinating updates, freshness)
- [ ] Write speaker notes
- [ ] Record Video 25 (slides + demo, no notebook)

### Video 26: Resilience (Module 25)
- [ ] Build slide deck (throttling, retries, circuit breakers, three-tier degradation)
- [ ] Write speaker notes
- [ ] Build notebook: 25-resilience.ipynb
- [ ] Record Video 26

### Video 27: Consistency and Idempotency (Module 26)
- [ ] Build slide deck (duplicate embeddings, versioning, atomic updates)
- [ ] Write speaker notes
- [ ] Record Video 27 (slides + demo, no notebook)

### Video 28: Privacy and Security (Module 27)
- [ ] Build slide deck (IAM, KMS, PII, GDPR, Bedrock Guardrails, red-teaming)
- [ ] Write speaker notes
- [ ] Build notebook: 27-privacy-security.ipynb
- [ ] Record Video 28

### Video 29: Production Deployment Patterns (Module 28)
- [ ] Build slide deck (blue/green for vector indexes, safe upgrades, gradual rollout)
- [ ] Write speaker notes
- [ ] Record Video 29 (slides + demo, no notebook)

### Video 30: Continuous Improvement (Module 29)
- [ ] Build slide deck (A/B testing retrieval, feedback loops, ranking improvement)
- [ ] Write speaker notes
- [ ] Build notebook: 29-continuous-improvement.ipynb
- [ ] Record Video 30

### Video 31: Emerging Patterns and Future Directions (Module 30)
- [ ] Build slide deck (agentic workflows, multimodal retrieval, where AWS AI is heading)
- [ ] Write speaker notes
- [ ] Record Video 31

---

## Phase 6: Course Wrap-up and Polish

- [ ] Build course wrap-up slides (what to do next, certifications, deeper reading, community)
- [ ] Record wrap-up video (~3 min)
- [ ] Build cost model spreadsheet (standalone learner reference)
- [ ] Create cheat sheets / reference cards (one per section)
- [ ] Final review: terminology consistency across all 30 modules
- [ ] Final review: all notebooks follow standard shape (what you'll do / prerequisites / cost estimate / setup / lesson / what you've built / extensions)
- [ ] Final review: all slide decks match visual standard (dark theme, fonts, colours, diagrams)
- [ ] Final review: UK English pass across all written content
- [ ] Update README.md with final notebook list and module map
- [ ] Tag final release on GitHub

---

## Infrastructure Blockers (build before dependent sections)

| Stack | Required before | Status |
|-------|----------------|--------|
| meridian-base.yaml | Everything | Deployed |
| meridian-vectors.yaml | ~~Folded into meridian-base~~ | N/A |
| meridian-web (frontends + API) | Section 1 (deploy with base) | Deployed |
| meridian-knowledge.yaml | Section 2 (Module 8+) | Not built |
| meridian-agents.yaml | Module 14 (Agents for Amazon Bedrock / AgentCore) | Not built |
| meridian-ops.yaml | Section 4 (Module 22+) | Not built |

---

## Summary Counts

| Asset type | Total needed | Done | Remaining |
|-----------|-------------|------|-----------|
| Videos | 31 + wrap-up | 1 | 31 |
| Slide decks | 31 | 2 | 29 |
| Notebooks | 22 | 0 | 22 |
| CloudFormation stacks | 5 | 2 | 3 |
| Frontends | 2 (Ridge Assist + Ridge Insight) | 0 | 2 |
| API layer (Lambda + APIGW) | 1 | 0 | 1 |
| Architecture diagrams | 2+ | 0 | 2+ |
| Evaluation harness | 1 | 0 | 1 |
| Cost model spreadsheet | 1 | 0 | 1 |
| Cheat sheets | 4 | 0 | 4 |
