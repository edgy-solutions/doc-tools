import os

import uvicorn

from doc_tools.api.app import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "3031")))
