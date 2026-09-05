# Third-Party Notices

The project's MIT license applies to its original source code, not to external
dependencies, API responses, articles, model weights, trademarks or container
images. Dependency sources are installed separately and are not vendored here.

## Frontend

Vue, Element Plus, Axios, Day.js, VueUse and their supporting packages primarily
use MIT terms. Lucide Vue uses ISC terms and includes additional icon notices;
other dependencies include BSD and Apache-2.0 components.

Exact upstream copyright and license texts for the lockfile's non-development,
non-optional packages are preserved in `frontend/public/THIRD_PARTY_LICENSES.txt`.
Vite copies that file into the built site. Regenerate it after dependency changes
with `node scripts/generate_frontend_notices.mjs`, and verify it with `--check`.

## Python

Direct dependency license metadata at the versions in `backend/requirements.txt`:

- MIT: FastAPI, SQLAlchemy, PyMySQL, Pydantic, PyYAML, APScheduler, redis-py,
  eval-type-backport, LangChain, python-docx and Alembic.
- Apache-2.0: Requests, bcrypt, qdrant-client, grpcio, grpcio-tools and python-multipart.
- Apache-2.0 OR BSD-3-Clause: cryptography.
- BSD: Uvicorn (3-Clause), protobuf (3-Clause), and pypdf (see its distributed LICENSE).

Transitive dependencies retain the licenses shipped in their distributions.
The environment's installed package license files remain the authoritative
notices when building or distributing a Python environment or container.

## Services and Assets

MySQL, Redis, Qdrant, Nginx, Node.js and Python container images are not included
in this source repository. Their version-specific distribution terms apply
separately. In particular, Redis server licensing varies by version and is not
the same as the MIT-licensed Python redis client. Review the actual image version
before redistributing an assembled deployment.

The application no longer loads Google Fonts automatically. Its font stacks use
locally available fonts and system fallbacks; no font files are redistributed.
Application-specific visual markup is original project code, while library icons
retain the notices referenced above.

Collected data and knowledge documents are excluded from this release. API access
does not transfer rights to reproduce the underlying content; see `docs/DATA_SOURCES.md`.
