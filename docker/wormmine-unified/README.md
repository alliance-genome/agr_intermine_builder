# WormMine Unified Docker Container

Single-container deployment of WormMine with Tomcat, Solr, and RDS PostgreSQL.

## Features

- **Java 8** - Required for InterMine
- **Gradle 4.9** - Build tool
- **Apache Tomcat 9.0.82** - Web application server
- **Apache Solr 8.4.1** - Search platform
- **Perl + CPAN** - All required modules for WormBase data processing
- **sudo** - For manual operations
- **RDS PostgreSQL** - External database (not in container)

## Quick Start

1. **Configure environment**:
```bash
cp .env.example .env
# Edit .env with your RDS credentials
```

2. **Build container**:
```bash
docker-compose build
```

3. **Start container**:
```bash
docker-compose up -d
```

4. **Access shell**:
```bash
docker exec -it wormmine bash
```

## Manual Operations

The container runs in **manual mode** by default - Solr and Tomcat do NOT auto-start. This allows you to run builds and data processing manually.

### Database Operations

```bash
# Access container
docker exec -it wormmine bash

# Build database schema
cd /opt/intermine/wormmine
./gradlew buildDB

# Integrate data sources
./gradlew integrate -Psource=wormbase-acedb
./gradlew integrate -Psource=go-annotation
# ... etc
```

### Start Solr (when needed)

```bash
# Inside container
sudo /opt/solr/bin/solr start -p 8983 -s /var/solr/data -m 4g
```

### Start Tomcat (when needed)

```bash
# Stop container and restart with tomcat mode
docker-compose stop
docker-compose run --rm wormmine tomcat
```

## Data Directories

- `/root/data` - Mounted from `./data` (AceDB dumps, FASTA, GFF3, etc.)
- `/opt/intermine/wormmine` - WormMine code
- `/opt/intermine/logs` - InterMine logs
- `/var/solr/data` - Solr indexes
- `/opt/tomcat/logs` - Tomcat logs

## Perl Modules

All required Perl modules are pre-installed:
- Moose, Time::HiRes, FindBin
- Digest::MD5, Log::Log4perl
- Bio::Perl, Bio::SeqIO
- LWP::UserAgent, HTTP::Date
- XML::DOM, XML::Simple, XML::Parser::PerlSAX
- And more...

## Environment Variables

See `.env.example` for all available environment variables.

Key variables:
- `RDS_HOST` - PostgreSQL hostname
- `RDS_PASSWORD` - PostgreSQL password
- `WORMBASE_RELEASE` - WormBase version (e.g., WS290)
- `DB_VERSION_SUFFIX` - Optional suffix for database name

## Database Names

Databases are auto-created on startup:
- `wormmine_ws290` (or your configured release)
- `wormmine_items` (staging database)
- `wormmine_userprofile` (user profiles)

## Useful Commands

```bash
# View logs
docker-compose logs -f

# Stop container
docker-compose down

# Rebuild container
docker-compose build --no-cache

# Access PostgreSQL from container
psql -h $RDS_HOST -U $RDS_USER -d wormmine_ws290
```

## Ports

- `8080` - Tomcat (when started)
- `8983` - Solr (when started)

## Notes

- Container user: `intermine` (uid 1000, has sudo access)
- Perl scripts in `/opt/intermine/wormmine/support/scripts/`
- `project_build` script available in PATH
- All WormBase Perl modules in `/opt/intermine/wormmine/support/perllib/`
