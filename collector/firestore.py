from __future__ import annotations

import os
from typing import Any, Optional


def firestore_enabled() -> bool:
    return bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") and os.environ.get("FIREBASE_PROJECT_ID"))


class FirestoreWriter:
    def __init__(self, collection: str = "press_items"):
        self.collection = collection
        self._db = None

    def _init(self):
        if self._db is not None:
            return
        import firebase_admin
        from firebase_admin import credentials, firestore

        proj = os.environ.get("FIREBASE_PROJECT_ID")
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if not proj or not cred_path:
            raise RuntimeError("Firestore not configured: set GOOGLE_APPLICATION_CREDENTIALS and FIREBASE_PROJECT_ID")

        if not firebase_admin._apps:
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred, {"projectId": proj})
        self._db = firestore.client()

    def upsert(self, item: dict[str, Any]):
        self._init()
        doc_id = item.get("id")
        if not doc_id:
            raise ValueError("item missing id")
        # Use merge so updates don't wipe server-side fields
        self._db.collection(self.collection).document(doc_id).set(item, merge=True)
