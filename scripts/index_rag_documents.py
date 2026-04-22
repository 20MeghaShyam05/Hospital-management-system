from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from features.llm.rag import RoleKnowledgeBase


def main() -> None:
    rag = RoleKnowledgeBase()
    result = rag.index_documents(Path(rag._docs_dir))
    print(
        f"Indexed {result['documents_indexed']} documents into pgvector "
        f"with {result['chunks_indexed']} chunks."
    )


if __name__ == "__main__":
    main()
