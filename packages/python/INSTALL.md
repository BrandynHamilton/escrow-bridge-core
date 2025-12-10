# Installation Guide

## Install from PyPI (when published)

```bash
# Using pip
pip install escrow-bridge-sdk

# Using uv
uv add escrow-bridge-sdk
```

## Install from Source (Local Development)

### 1. Navigate to the package directory

```bash
cd E:\Projects\escrow_bridge\packages\python
```

### 2. Install in editable mode

```bash
# Using pip
pip install -e .

# Or with uv
uv pip install -e .
```

### 3. Install with development dependencies

```bash
# Using pip
pip install -e ".[dev]"

# Or with uv
uv pip install -e ".[dev]"
```

## Build the Package

### Using build tool

```bash
# Install build tool
pip install build

# Build the package
python -m build

# This creates dist/escrow_bridge_sdk-0.1.0-py3-none-any.whl
# and dist/escrow-bridge-sdk-0.1.0.tar.gz
```

### Using hatch

```bash
# Install hatch
pip install hatch

# Build
hatch build
```

## Install from Built Wheel

```bash
pip install dist/escrow_bridge_sdk-0.1.0-py3-none-any.whl
```

## Verify Installation

```python
python -c "from escrow_bridge_sdk import EscrowBridgeSDK; print('SDK imported successfully!')"
```

## Publishing to PyPI (For Maintainers)

### 1. Build the package

```bash
python -m build
```

### 2. Upload to TestPyPI (optional, for testing)

```bash
pip install twine
twine upload --repository testpypi dist/*
```

### 3. Upload to PyPI

```bash
twine upload dist/*
```

## Troubleshooting

### Missing dependencies

If you encounter import errors, ensure httpx is installed:

```bash
pip install httpx>=0.24.0
```

### Build errors

Make sure you have the latest build tools:

```bash
pip install --upgrade build setuptools wheel
```
