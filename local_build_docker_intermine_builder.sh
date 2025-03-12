docker build \
  -t 100225593120.dkr.ecr.us-east-1.amazonaws.com/agr_intermine_builder_env:stage \
  --no-cache \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  --progress=plain \
  -f intermine_builder/intermine_builder.Dockerfile intermine_builder