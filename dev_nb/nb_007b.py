
        #################################################
        ### THIS FILE WAS AUTOGENERATED! DO NOT EDIT! ###
        #################################################
        # file to edit: dev_nb/007b_imdb_classifier.ipynb

from nb_007a import *

def convert_weights(wgts, stoi_wgts, itos_new):
    dec_bias, enc_wgts = wgts['1.decoder.bias'], wgts['0.encoder.weight']
    bias_m, wgts_m = dec_bias.mean(0), enc_wgts.mean(0)
    new_w = enc_wgts.new_zeros((len(itos_new),enc_wgts.size(1))).zero_()
    new_b = dec_bias.new_zeros((len(itos_new),)).zero_()
    for i,w in enumerate(itos_new):
        r = stoi_wgts[w] if w in stoi_wgts else -1
        new_w[i] = enc_wgts[r] if r>=0 else wgts_m
        new_b[i] = dec_bias[r] if r>=0 else bias_m
    wgts['0.encoder.weight'] = new_w
    wgts['0.encoder_dp.emb.weight'] = new_w.clone()
    wgts['1.decoder.weight'] = new_w.clone()
    wgts['1.decoder.bias'] = new_b
    return wgts

def save_encoder(learn, name):
    torch.save(learn.model[0].state_dict(), learn.path/f'{name}.pth')

from torch.utils.data import Sampler, BatchSampler

class SortSampler(Sampler):
    "Go through the text data by order of length"

    def __init__(self, data_source, key): self.data_source,self.key = data_source,key
    def __len__(self): return len(self.data_source)
    def __iter__(self):
        return iter(sorted(range(len(self.data_source)), key=self.key, reverse=True))


class SortishSampler(Sampler):
    "Go through the text data by order of length with a bit of randomness"

    def __init__(self, data_source, key, bs):
        self.data_source,self.key,self.bs = data_source,key,bs

    def __len__(self): return len(self.data_source)

    def __iter__(self):
        idxs = np.random.permutation(len(self.data_source))
        sz = self.bs*50
        ck_idx = [idxs[i:i+sz] for i in range(0, len(idxs), sz)]
        sort_idx = np.concatenate([sorted(s, key=self.key, reverse=True) for s in ck_idx])
        sz = self.bs
        ck_idx = [sort_idx[i:i+sz] for i in range(0, len(sort_idx), sz)]
        max_ck = np.argmax([self.key(ck[0]) for ck in ck_idx])  # find the chunk with the largest key,
        ck_idx[0],ck_idx[max_ck] = ck_idx[max_ck],ck_idx[0]     # then make sure it goes first.
        sort_idx = np.concatenate(np.random.permutation(ck_idx[1:]))
        sort_idx = np.concatenate((ck_idx[0], sort_idx))
        return iter(sort_idx)

def pad_collate(samples, pad_idx=1, pad_first=True):
    max_len = max([len(s[0]) for s in samples])
    res = torch.zeros(max_len, len(samples)).long() + pad_idx
    for i,s in enumerate(samples): res[-len(s[0]):,i] = LongTensor(s[0])
    return res, LongTensor([s[1] for s in samples]).squeeze()

class MultiBatchRNNCore(RNNCore):
    def __init__(self, bptt, max_seq, *args, **kwargs):
        self.max_seq,self.bptt = max_seq,bptt
        super().__init__(*args, **kwargs)

    def concat(self, arrs):
        return [torch.cat([l[si] for l in arrs]) for si in range(len(arrs[0]))]

    def forward(self, input):
        sl,bs = input.size()
        self.reset()
        raw_outputs, outputs = [],[]
        for i in range(0, sl, self.bptt):
            r, o = super().forward(input[i: min(i+self.bptt, sl)])
            if i>(sl-self.max_seq):
                raw_outputs.append(r)
                outputs.append(o)
        return self.concat(raw_outputs), self.concat(outputs)

def bn_dp_lin(n_in, n_out, drop, relu=True):
    layers = [nn.BatchNorm1d(n_in), nn.Dropout(drop), nn.Linear(n_in, n_out)]
    if relu: layers.append(nn.ReLU(inplace=True))
    return layers

class PoolingLinearClassifier(nn.Module):
    def __init__(self, layers, drops):
        super().__init__()
        lyrs = []
        for i in range(len(layers)-1):
            lyrs += bn_dp_lin(layers[i], layers[i + 1], drops[i], i!=len(layers)-2)
        self.layers = nn.Sequential(*lyrs)

    def pool(self, x, bs, is_max):
        f = F.adaptive_max_pool1d if is_max else F.adaptive_avg_pool1d
        return f(x.permute(1,2,0), (1,)).view(bs,-1)

    def forward(self, input):
        raw_outputs, outputs = input
        output = outputs[-1]
        sl,bs,_ = output.size()
        avgpool = self.pool(output, bs, False)
        mxpool = self.pool(output, bs, True)
        x = torch.cat([output[-1], mxpool, avgpool], 1)
        x = self.layers(x)
        return x, raw_outputs, outputs

def get_rnn_classifier(bptt, max_seq, n_class, vocab_sz, emb_sz, n_hid, n_layers, pad_token, layers, drops,
                       bidir=False, qrnn=False, hidden_p=0.2, input_p=0.6, embed_p=0.1, weight_p=0.5):
    rnn_enc = MultiBatchRNNCore(bptt, max_seq, vocab_sz, emb_sz, n_hid, n_layers, pad_token=pad_token, bidir=bidir,
                      qrnn=qrnn, hidden_p=hidden_p, input_p=input_p, embed_p=embed_p, weight_p=weight_p)
    return SequentialRNN(rnn_enc, PoolingLinearClassifier(layers, drops))

def load_encoder(learn, name):
    learn.model[0].load_state_dict(torch.load(learn.path/f'{name}.pth'))