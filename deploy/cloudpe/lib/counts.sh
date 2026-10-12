#!/usr/bin/env bash
# counts.sh — exact row/document counts, used by the capture scripts (source
# side) and the restore scripts (target side) so the two can be diffed.
# Source, don't run. Output is "name<TAB>count", byte-sorted.

# pg_table_counts <container> <user> <db>
# Every base table outside the system and TimescaleDB-internal schemas. A
# hypertable is counted through its parent, so chunk tables are not listed.
pg_table_counts() {
    local c="$1" u="$2" d="$3"
    # </dev/null: `docker exec -i` would otherwise swallow the caller's stdin.
    docker exec -i "$c" psql -U "$u" -d "$d" -At -v ON_ERROR_STOP=1 </dev/null -c "
        SELECT format('SELECT %L, count(*) FROM %I.%I;',
                      table_schema || '.' || table_name, table_schema, table_name)
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema !~ '^(pg_|_timescaledb_|timescaledb_|information_schema\$)'
        ORDER BY 1;" \
    | docker exec -i "$c" psql -U "$u" -d "$d" -At -F $'\t' -v ON_ERROR_STOP=1 \
    | LC_ALL=C sort
}

# mongo_coll_counts <container> <root-user> <root-password>
# Every collection in every non-system database.
mongo_coll_counts() {
    local js='
        db.getMongo().getDBNames()
          .filter(n => !["admin", "config", "local"].includes(n)).sort()
          .forEach(n => {
            const d = db.getSiblingDB(n);
            d.getCollectionNames().sort().forEach(c => {
              if (c.startsWith("system.")) return;
              print(n + "." + c + "\t" + d.getCollection(c).countDocuments({}));
            });
          });'
    # Values go through the docker client's environment (-e NAME with no value)
    # so the password never appears in a host process list.
    MONGO_U="$2" MONGO_PW="$3" JS="$js" docker exec -e MONGO_U -e MONGO_PW -e JS "$1" \
        sh -c 'mongosh --quiet -u "$MONGO_U" -p "$MONGO_PW" --authenticationDatabase admin --eval "$JS"' \
    | LC_ALL=C sort
}

# compare_counts <label> <source.tsv> <target.tsv>
# Prints a summary and the differing lines. Returns 1 if anything differs.
compare_counts() {
    local label="$1" src="$2" dst="$3" total
    total=$(wc -l < "$src")
    if diff -q "$src" "$dst" >/dev/null; then
        echo "[counts] ${label}: all ${total} entries match the source."
        return 0
    fi
    echo "[counts] ${label}: DIFFERS from the source (< source, > restored):"
    diff "$src" "$dst" | grep -E '^[<>]' | head -100
    return 1
}
