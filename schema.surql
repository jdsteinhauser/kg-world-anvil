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
DEFINE FIELD OVERWRITE attributes ON entity TYPE object FLEXIBLE DEFAULT {};
DEFINE FIELD OVERWRITE embedding ON entity TYPE option<array<float>> DEFAULT NONE;
DEFINE FIELD OVERWRITE source_documents ON entity TYPE array<record<document>> DEFAULT [];
DEFINE FIELD OVERWRITE created_at ON entity TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE updated_at ON entity TYPE datetime DEFAULT time::now();
DEFINE INDEX OVERWRITE entity_canonical_idx ON entity FIELDS canonical_key, type UNIQUE;

-- Relation tables (e.g. parent_of, located_in, knows) are defined dynamically at ingest time
-- via DEFINE TABLE <predicate> TYPE RELATION FROM entity TO entity SCHEMAFULL.
