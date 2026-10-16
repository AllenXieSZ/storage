# build data dir: 50 config json, tokenizer.json (BPE trained on synthetic text), 8 .npy index files (64MiB each)
import os, sys, json, numpy as np
from tokenizers import Tokenizer, models, trainers, pre_tokenizers
D = sys.argv[1]; os.makedirs(D + '/cfg', exist_ok=True); os.makedirs(D + '/idx', exist_ok=True)
for i in range(50):
    json.dump({'hidden_size': 8192, 'layers': 80, 'name': f'cfg{i}', 'pad': list(range(2000))}, open(f'{D}/cfg/c{i:02d}.json', 'w'))
tk = Tokenizer(models.BPE(unk_token='[UNK]')); tk.pre_tokenizer = pre_tokenizers.Whitespace()
rng = np.random.default_rng(0); words = [''.join(rng.choice(list('abcdefghijklmnopqrstuvwxyz'), rng.integers(2, 10))) for _ in range(20000)]
text = [' '.join(rng.choice(words, 50)) for _ in range(20000)]
tk.train_from_iterator(text, trainers.BpeTrainer(vocab_size=32000, special_tokens=['[UNK]']))
tk.save(f'{D}/tokenizer.json')
for i in range(8):
    np.save(f'{D}/idx/doc_idx_{i}.npy', np.arange(8 << 20, dtype=np.int64))
print('ok', os.path.getsize(f'{D}/tokenizer.json'))
