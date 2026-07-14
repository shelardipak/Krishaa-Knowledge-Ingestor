
import os
from langchain_openai import OpenAIEmbeddings
from qdrant_client import QdrantClient
from rag_ingestion.config import Settings

s = Settings()
os.environ["OPENAI_API_KEY"] = s.openai_api_key

client = QdrantClient(
    url=s.qdrant_url,
    api_key=s.qdrant_api_key,
    check_compatibility=s.qdrant_check_compatibility,
)

query = "Screened Coupling Connectors RSTI-CC-X9 Large Cross Sections, 1250A up to 42 kV single core branch off"
embedder = OpenAIEmbeddings(model=s.embedding_model, dimensions=s.embedding_dimensions)
vector = embedder.embed_query(query)

result = client.query_points(
    collection_name=s.qdrant_collection,
    query=vector,
    using=s.qdrant_vector_name or None,
    limit=3,
    with_payload=True,
)

for point in result.points:
    p = point.payload
    print("\nScore:", point.score)
    print("Vendor:", p.get("vendor"))
    print("Source:", p.get("source_file"))
    print("Page:", p.get("page_number"))
    print("Type:", p.get("chunk_type"))
    print("Image:", p.get("image_url"))
    print("Text:", (p.get("text") or "")[:500])
