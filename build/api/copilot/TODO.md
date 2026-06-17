# BillerQ AI Copilot - Implementation Tasks

## Phase 1: Fix Navigation & Routes (CRITICAL - BLOCKING)
- [ ] Fix PAGE_MAP with actual routes extracted from React bundle
- [ ] Fix navigation to use new tab for protected routes (preserves auth state)
- [ ] Fix widget to mount on all authenticated pages
- [ ] Fix auth token extraction

## Phase 2: Multi-Tenant Security
- [ ] Extract company_id from login data
- [ ] Pass company_id in API calls
- [ ] Filter all data by company_id

## Phase 3: Database Connection
- [ ] Add MySQL database connection
- [ ] Customer search by name/area
- [ ] Payment/collection queries

## Phase 4: Smart Search
- [ ] Fuzzy customer name matching
- [ ] Location-based search (area, city)

## Phase 5: Analytics Engine
- [ ] Trend data extraction
- [ ] Ollama-powered business insights

## Phase 6: Amazon Bedrock Migration (Readiness)
- [ ] LLMProvider abstract class
- [ ] OllamaProvider implementation
- [ ] BedrockProvider implementation (Claude Sonnet)
- [ ] Auto-switch via env flag

## Phase 7: Enhanced Widget UX
- [ ] Better error handling
- [ ] Conversation history display
- [ ] Typing improvements
- [ ] Mobile responsiveness fixes