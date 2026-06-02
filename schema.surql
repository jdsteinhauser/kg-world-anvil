OPTION IMPORT;

-- Knowledge graph schema for kg-world-anvil

DEFINE TABLE OVERWRITE document SCHEMAFULL;
DEFINE FIELD OVERWRITE raw ON document TYPE string;
DEFINE FIELD OVERWRITE format ON document TYPE string;
DEFINE FIELD OVERWRITE content_hash ON document TYPE string;
DEFINE FIELD OVERWRITE ingested_at ON document TYPE datetime DEFAULT time::now();
DEFINE INDEX OVERWRITE document_hash_idx ON document FIELDS content_hash UNIQUE;

DEFINE TABLE OVERWRITE entity SCHEMAFULL;
DEFINE FIELD OVERWRITE name ON entity TYPE string;
DEFINE FIELD OVERWRITE canonical_key ON entity TYPE string;
DEFINE FIELD OVERWRITE type ON entity TYPE string;
DEFINE FIELD OVERWRITE aliases ON entity TYPE array<string> DEFAULT [];
DEFINE FIELD OVERWRITE broader_types ON entity TYPE array<string> DEFAULT [];
DEFINE FIELD OVERWRITE attributes ON entity TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD OVERWRITE embedding ON entity TYPE option<array<float>> DEFAULT NONE;
DEFINE FIELD OVERWRITE source_documents ON entity TYPE array<record<document>> DEFAULT [];
DEFINE FIELD OVERWRITE source_chunks ON entity TYPE array<record<chunk>> DEFAULT [];
DEFINE FIELD OVERWRITE created_at ON entity TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE updated_at ON entity TYPE datetime DEFAULT time::now();
DEFINE INDEX OVERWRITE entity_canonical_idx ON entity FIELDS canonical_key, type UNIQUE;

-- RAG text chunks (smaller spans than extraction chunks; vector-indexed for retrieval)
DEFINE TABLE OVERWRITE chunk SCHEMAFULL;
DEFINE FIELD OVERWRITE document ON chunk TYPE record<document>;
DEFINE FIELD OVERWRITE seq ON chunk TYPE int;
DEFINE FIELD OVERWRITE text ON chunk TYPE string;
DEFINE FIELD OVERWRITE start_char ON chunk TYPE int DEFAULT 0;
DEFINE FIELD OVERWRITE end_char ON chunk TYPE int DEFAULT 0;
DEFINE FIELD OVERWRITE embedding ON chunk TYPE option<array<float>> DEFAULT NONE;
DEFINE FIELD OVERWRITE created_at ON chunk TYPE datetime DEFAULT time::now();
DEFINE INDEX OVERWRITE chunk_doc_seq_idx ON chunk FIELDS document, seq UNIQUE;
DEFINE INDEX OVERWRITE chunk_embedding_idx ON chunk FIELDS embedding HNSW DIMENSION 1536 DIST COSINE;

-- Relation tables (e.g. parent_of, located_in, knows) are defined dynamically at ingest time
-- via DEFINE TABLE <predicate> TYPE RELATION FROM entity TO entity SCHEMAFULL.

-- Staging graph (draft extractions before promote to production)

DEFINE TABLE OVERWRITE staging_batch SCHEMAFULL;
DEFINE FIELD OVERWRITE document ON staging_batch TYPE record<document>;
DEFINE FIELD OVERWRITE status ON staging_batch TYPE string;
DEFINE FIELD OVERWRITE created_at ON staging_batch TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE updated_at ON staging_batch TYPE datetime DEFAULT time::now();
DEFINE INDEX OVERWRITE staging_batch_status_idx ON staging_batch FIELDS status;

DEFINE TABLE OVERWRITE staging_entity SCHEMAFULL;
DEFINE FIELD OVERWRITE batch ON staging_entity TYPE record<staging_batch>;
DEFINE FIELD OVERWRITE name ON staging_entity TYPE string;
DEFINE FIELD OVERWRITE canonical_key ON staging_entity TYPE string;
DEFINE FIELD OVERWRITE type ON staging_entity TYPE string;
DEFINE FIELD OVERWRITE aliases ON staging_entity TYPE array<string> DEFAULT [];
DEFINE FIELD OVERWRITE broader_types ON staging_entity TYPE array<string> DEFAULT [];
DEFINE FIELD OVERWRITE attributes ON staging_entity TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD OVERWRITE embedding ON staging_entity TYPE option<array<float>> DEFAULT NONE;
DEFINE FIELD OVERWRITE source_chunks ON staging_entity TYPE array<record<chunk>> DEFAULT [];
DEFINE FIELD OVERWRITE created_at ON staging_entity TYPE datetime DEFAULT time::now();
DEFINE INDEX OVERWRITE staging_entity_batch_key_type_idx ON staging_entity FIELDS batch, canonical_key, type UNIQUE;

-- Staging relation tables: staging_<predicate> TYPE RELATION FROM staging_entity TO staging_entity
-- defined dynamically at extract time (see db/relations.py ensure_staging_relation_table).
