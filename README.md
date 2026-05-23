```sh
uv run hypercorn main:app --config hypercorn.toml
```

```sh
docker buildx build --platform linux/arm64 -t docker.io/winston0410/test:0.2.0 .
```
