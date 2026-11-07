# Backend only. Deploy from the repository root; Vercel continues to build web/.
FROM node:22-bookworm-slim AS adapters
WORKDIR /app
COPY integrations/ens/package*.json integrations/ens/
RUN npm --prefix integrations/ens ci --omit=dev
COPY integrations/arkiv/package*.json integrations/arkiv/
RUN npm --prefix integrations/arkiv ci --omit=dev
COPY integrations/ens/ integrations/ens/
COPY integrations/arkiv/ integrations/arkiv/
COPY deploy/compiler/package*.json /compiler/
RUN npm --prefix /compiler ci --omit=dev
COPY contracts/src/ contracts/src/
COPY contracts/scripts/compile.mjs contracts/scripts/compile.mjs
RUN MEMORYSEAL_NODE_MODULES=/compiler/node_modules node contracts/scripts/compile.mjs

COPY sdk/typescript/package*.json sdk/typescript/
RUN npm --prefix sdk/typescript ci
COPY sdk/typescript/ sdk/typescript/
RUN npm --prefix sdk/typescript run build

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=adapters /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
# Editable install preserves repository-relative adapter/artifact paths.
RUN pip install --no-cache-dir -e '.[bridge-verification]'
COPY --from=adapters /app/integrations/ integrations/
COPY --from=adapters /app/contracts/artifacts/ contracts/artifacts/
COPY deploy/start_gateway.py deploy/start_gateway.py
COPY --from=adapters /app/sdk/typescript/ sdk/typescript/
COPY web/lib/payment-demo.mjs web/lib/sepolia-demo-server.mjs web/lib/sepolia-demo-workflow.mjs web/lib/
COPY web/scripts/hosted-demo-worker.mjs web/scripts/
# Worker imports viem from the SDK dependency tree without installing Next.js.
RUN mkdir -p web/node_modules && ln -s /app/sdk/typescript/node_modules/viem web/node_modules/viem
ENV MEMORYSEAL_DATABASE_URL=sqlite:////data/memoryseal.db
EXPOSE 8000
CMD ["python", "deploy/start_gateway.py"]
