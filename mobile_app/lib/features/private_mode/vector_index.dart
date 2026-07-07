import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:isolate';
import 'dart:typed_data';

/// One semantic-search hit: the pack block plus its similarity rank.
class VectorHit {
  final String docId;
  final String blockId;
  final double score; // integer dot product, normalized to ~0..1
  const VectorHit(this.docId, this.blockId, this.score);
}

/// Loads the pack's precomputed int8 EmbeddingGemma vectors and answers
/// nearest-neighbour queries. The 89 MB blob and the O(n·dim) scan live in a
/// dedicated isolate so retrieval never janks the chat UI.
///
/// Query path (must mirror scripts/build_pack_vectors.py): embed the query
/// with EmbeddingGemma (retrievalQuery), L2-normalize, int8-quantize at the
/// same scale (127), then rank by integer dot product — monotonic in cosine
/// for identically-quantized unit vectors.
class VectorIndex {
  final Isolate _isolate;
  final SendPort _tx;

  VectorIndex._(this._isolate, this._tx);

  static const double scale = 127.0;

  static Future<VectorIndex?> load({
    required String blobPath,
    required String idxPath,
    required String metaPath,
  }) async {
    try {
      final meta = jsonDecode(await File(metaPath).readAsString())
          as Map<String, dynamic>;
      final dim = meta['dim'] as int? ?? 768;
      final count = meta['count'] as int? ?? 0;
      if (count <= 0) return null;

      final ready = ReceivePort();
      final isolate = await Isolate.spawn(
        _worker,
        _InitMsg(ready.sendPort, blobPath, idxPath, dim, count),
      );
      // First message from the worker is its command SendPort (after load).
      final tx = await ready.first as SendPort;
      ready.close();
      return VectorIndex._(isolate, tx);
    } catch (_) {
      return null;
    }
  }

  /// Top-[topK] blocks for an already-quantized query vector.
  Future<List<VectorHit>> search(Int8List query, {int topK = 8}) async {
    final reply = ReceivePort();
    _tx.send(_QueryMsg(reply.sendPort, query, topK));
    final result = await reply.first as List;
    reply.close();
    return result.cast<VectorHit>();
  }

  void dispose() {
    _isolate.kill(priority: Isolate.immediate);
  }

  // ── Worker isolate ────────────────────────────────────────────────────────
  static void _worker(_InitMsg init) {
    Int8List blob;
    final docIds = <String>[];
    final blockIds = <String>[];
    try {
      blob = File(init.blobPath).readAsBytesSync().buffer.asInt8List();
      final lines = File(init.idxPath).readAsLinesSync();
      for (final line in lines) {
        if (line.isEmpty) continue;
        final tab = line.indexOf('\t');
        if (tab < 0) continue;
        docIds.add(line.substring(0, tab));
        blockIds.add(line.substring(tab + 1));
      }
    } catch (_) {
      // Signal failure by closing without a command port; load() will hang
      // only if this throws before the first send, so send a dead port.
      final dead = ReceivePort();
      init.ready.send(dead.sendPort);
      dead.close();
      return;
    }

    final dim = init.dim;
    final n = docIds.length;
    final commands = ReceivePort();
    init.ready.send(commands.sendPort);

    commands.listen((msg) {
      if (msg is! _QueryMsg) return;
      final q = msg.query;
      final k = msg.topK;
      // Parallel arrays for a cheap bounded top-k (k is small).
      final bestScore = List<int>.filled(k, -1 << 62);
      final bestIdx = List<int>.filled(k, -1);
      for (var row = 0; row < n; row++) {
        final base = row * dim;
        var dot = 0;
        for (var d = 0; d < dim; d++) {
          dot += blob[base + d] * q[d];
        }
        // Insert into the running top-k if it beats the current minimum.
        if (dot > bestScore[k - 1]) {
          var pos = k - 1;
          while (pos > 0 && bestScore[pos - 1] < dot) {
            bestScore[pos] = bestScore[pos - 1];
            bestIdx[pos] = bestIdx[pos - 1];
            pos--;
          }
          bestScore[pos] = dot;
          bestIdx[pos] = row;
        }
      }
      // Normalize integer dot product to ~0..1 (unit vectors × scale²).
      final norm = scale * scale;
      final hits = <VectorHit>[];
      for (var i = 0; i < k; i++) {
        final row = bestIdx[i];
        if (row < 0) break;
        hits.add(VectorHit(
          docIds[row],
          blockIds[row],
          (bestScore[i] / norm).clamp(0.0, 1.0),
        ));
      }
      msg.reply.send(hits);
    });
  }
}

class _InitMsg {
  final SendPort ready;
  final String blobPath;
  final String idxPath;
  final int dim;
  final int count;
  const _InitMsg(this.ready, this.blobPath, this.idxPath, this.dim, this.count);
}

class _QueryMsg {
  final SendPort reply;
  final Int8List query;
  final int topK;
  const _QueryMsg(this.reply, this.query, this.topK);
}
