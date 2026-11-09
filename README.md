# EU Security & Privacy Document Intelligence Navigator

Azure-based portfolio project that turns official EU and German security and privacy documents into searchable, traceable knowledge.

> Information-retrieval demonstrator only. It does not provide legal advice or compliance certification.

## Goal

Build a responsible document-intelligence application that:

- ingests openly reusable official documents in PDF, HTML, XML, and JSON formats;
- extracts document text, layout, headings, and tables;
- normalises documents into searchable sections;
- returns source-linked results with document, page, and section references;
- screens public queries with Azure AI Content Safety.

## Azure Services

- Azure AI Document Intelligence
- Azure AI Search
- Azure AI Content Safety
- Azure Functions
- Azure Static Web Apps
- Azure Storage
- Microsoft Entra ID and RBAC
- Cost Management

## Application Stack

- Python and FastAPI
- React and TypeScript
- Docker
- GitHub Actions
- Bicep infrastructure-as-code
- Pytest and Ruff

## Initial Source Areas

- GDPR / DSGVO
- EU AI Act
- NIS2
- Bundesdatenschutzgesetz (BDSG)
- BSI-Gesetz (BSIG)
- Selected openly reusable NIST publications

Full ISO standards and private/customer documents are deliberately excluded.

## Responsible Data Handling

Only official sources with documented reuse rights are included. The repository stores source metadata, licence notes, hashes, and reproducible download logic—not private data or Azure credentials.

See [Source Policy](docs/source-policy.md).

## Project Status

**Stage 0 — Foundation**

- [x] Azure resource group and cost budget
- [x] Public GitHub repository
- [ ] Source registry and licence verification
- [ ] Local ingestion pipeline
- [ ] Azure Document Intelligence integration
- [ ] Azure AI Search integration
- [ ] Content Safety integration
- [ ] Public deployment

## Licence

The project source code is released under the MIT License. Third-party documents remain subject to their respective official reuse terms.