"""Lossless completed-report storage. Never removes or replaces source reports."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
from .common import outside_package, relative

CHUNK = 1024 * 1024


def digest(path):
    sha = hashlib.sha256()
    size = 0
    with Path(path).open('rb') as stream:
        while block := stream.read(CHUNK):
            sha.update(block)
            size += len(block)
    return size, sha.hexdigest()


def expand(archive, expected_size, expected_hash, output=None):
    sha = hashlib.sha256()
    size = 0
    with gzip.open(archive, 'rb') as stream:
        while block := stream.read(min(CHUNK, expected_size - size + 1)):
            size += len(block)
            if size > expected_size:
                raise ValueError('Expanded report exceeds manifest size')
            sha.update(block)
            if output is not None:
                output.write(block)
    if size != expected_size or sha.hexdigest() != expected_hash:
        raise ValueError('Restored report does not match original SHA-256/size')


def archive_report(source, archive, *, provenance=None):
    source, archive = Path(source).resolve(), Path(archive).absolute()
    outside_package(archive)
    manifest = Path(str(archive) + '.manifest.json')
    if source.suffix.lower() != '.json':
        raise ValueError('Select an explicit completed .json report')
    if archive.exists() or manifest.exists():
        raise FileExistsError('Archive or manifest already exists; refusing overwrite')
    archive_created = manifest_created = False
    try:
        with source.open('rb') as src, archive.open('xb') as dst:
            archive_created = True
            before = source.stat()
            sha = hashlib.sha256()
            size = 0
            with gzip.GzipFile(filename='', mode='wb', fileobj=dst,
                               compresslevel=6, mtime=0) as compressed:
                while block := src.read(CHUNK):
                    sha.update(block)
                    size += len(block)
                    compressed.write(block)
        original_hash = sha.hexdigest()
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Source changed during capture; keep it active')
        if digest(source) != (size, original_hash):
            raise ValueError('Source content changed during capture')
        if provenance and original_hash != provenance['result_sha256']:
            raise ValueError('Source changed after receipt validation')
        expand(archive, size, original_hash)
        archive_size, archive_hash = digest(archive)
        record = {
            'schema': 'lossless-report-gzip-v1',
            'source_path': str(source), 'source_bytes': size,
            'source_sha256': original_hash, 'source_mtime_ns': before.st_mtime_ns,
            'archive_name': archive.name, 'archive_bytes': archive_size,
            'archive_sha256': archive_hash,
            'round_trip': 'sha256-and-byte-count-verified',
            'original_removed': False,
            'scope': 'Storage only; no measurement/schema/precision changes',
            'provenance': provenance,
        }
        with manifest.open('x', encoding='utf-8') as stream:
            manifest_created = True
            json.dump(record, stream, indent=2)
            stream.write('\n')
        return record
    except BaseException:
        if manifest_created:
            manifest.unlink(missing_ok=True)
        if archive_created:
            archive.unlink(missing_ok=True)
        raise


def verify_archive(archive):
    archive = Path(archive)
    record = json.loads(Path(str(archive) + '.manifest.json').read_text(encoding='utf-8'))
    if record.get('schema') != 'lossless-report-gzip-v1':
        raise ValueError('Unsupported archive manifest')
    size = record['source_bytes']
    if type(size) is not int or size < 0:
        raise ValueError('Invalid restored size')
    provenance = record.get('provenance')
    if provenance is not None:
        saved = {}
        for key in ('exit_receipt', 'owned_launch'):
            raw = base64.b64decode(provenance[key]['bytes_base64'], validate=True)
            if hashlib.sha256(raw).hexdigest() != provenance[key]['sha256']:
                raise ValueError('Preserved receipt hash mismatch')
            saved[key] = json.loads(raw)
        rows = [r for r in saved['exit_receipt'].get('result_files', [])
                if r.get('path') == provenance['result_path']]
        if (len(rows) != 1 or not rows[0].get('present')
                or any(rows[0].get(k) for k in ('stale', 'escaped', 'unreadable'))
                or rows[0].get('sha256') != record['source_sha256']
                or provenance['result_sha256'] != record['source_sha256']
                or any(r.get('label') != provenance['label'] for r in saved.values())):
            raise ValueError('Archive does not match preserved launch result')
    if digest(archive) != (record['archive_bytes'], record['archive_sha256']):
        raise ValueError('Archive SHA-256/size mismatch')
    expand(archive, size, record['source_sha256'])
    return record


def restore_report(archive, output):
    record = verify_archive(archive)
    output = Path(output)
    outside_package(output)
    created = False
    try:
        with output.open('xb') as stream:
            created = True
            expand(archive, record['source_bytes'], record['source_sha256'], stream)
        return {'restored_path': str(output.resolve()), 'sha256': record['source_sha256']}
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise


def _snapshot(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(4 * CHUNK + 1)
    if len(raw) > 4 * CHUNK:
        raise ValueError('Receipt exceeds 4 MiB bound')
    return json.loads(raw), {'path': str(Path(path).resolve()),
                           'sha256': hashlib.sha256(raw).hexdigest(),
                           'bytes_base64': base64.b64encode(raw).decode('ascii')}


def linked_archive(project, receipt, source, archive, *, completed=False):
    """Bind one declared result to immutable copies of its existing launch records."""
    if not completed:
        raise ValueError('Confirm producer completion before archiving')
    root = Path(project).resolve()
    source = Path(source).resolve()
    source.relative_to(root)
    receipt = Path(receipt).resolve()
    receipt.relative_to(root)
    record, saved_exit = _snapshot(receipt)
    launch, saved_launch = _snapshot(receipt.parent / 'owned-launch.json')
    survivors = record.get('survivors')
    survivors_clear = survivors == [] or (isinstance(survivors, dict)
        and survivors.get('status') == 'ok' and survivors.get('stopped') is True
        and not survivors.get('unstopped_pids') and not survivors.get('unverified'))
    if (record.get('kind') != 'launch-exit' or launch.get('kind') != 'owned-launch'
            or not record.get('finished_utc')
            or record.get('status') not in ('completed', 'failed', 'timed_out')
            or not survivors_clear
            or not record.get('label') or record['label'] != launch.get('label')
            or Path(launch.get('project', '')).resolve() != root):
        raise ValueError('Need paired terminal launch records for this project, with no survivors')
    matches = []
    for row in record.get('result_files', []):
        target = relative(root, row['path'])
        if target == source:
            matches.append(row)
    if len(matches) != 1:
        raise ValueError('Source must be exactly one declared result in the exit receipt')
    row = matches[0]
    if (not row.get('present') or any(row.get(k) for k in ('stale', 'escaped', 'unreadable'))
            or digest(source)[1] != row.get('sha256')):
        raise ValueError('Source does not match the fresh result recorded at exit')
    provenance = {'kind': 'studio-launch-result', 'label': record['label'],
                  'result_path': row['path'], 'result_sha256': row['sha256'],
                  'exit_receipt': saved_exit, 'owned_launch': saved_launch,
                  'limits': 'Preserves recorded identity; does not add missing source identity or acceptance'}
    return archive_report(source, archive, provenance=provenance)
