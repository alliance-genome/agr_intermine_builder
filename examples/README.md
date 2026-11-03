# Build-machine examples

Run these from the repository root after configuring the selected mine's `.env`.

```bash
./mine --dry-run alliancemine image
./mine alliancemine image
./mine alliancemine build --skip-stages deploy
./mine alliancemine logs -f
```

Inspect or run a specific tool:

```bash
./mine mousemine shell
./mine mousemine run bash -c 'cd /root/mousemine && ./gradlew :webapp:war --stacktrace'
./mine wormmine run /root/scripts/find_and_copy_wormbase_files.sh /root/data/wormbase
./mine flymine compose ps --all
```

For automation, invoke `mine` as a normal subprocess and check its exit status.
There is no separate Python orchestration API. See the [command guide](../README.md).
