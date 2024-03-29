# -*- coding: utf-8 -*-
# @Author: Jie Yang
# @Date:   2017-10-17 16:47:32
# @Last Modified by:   Jie Yang,     Contact: jieynlp@gmail.com
# @Last Modified time: 2018-03-30 16:20:07

import torch
import torch.autograd as autograd
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from wordsequence import WordSequence
from crf import CRF
from torch.autograd import Variable


class SeqModel(nn.Module):

    def __init__(self, data):
        super(SeqModel, self).__init__()
        self.use_crf = data.use_crf
        print "build network..."
        print "use_char: ", data.use_char
        if data.use_char:
            print "char feature extractor: ", data.char_feature_extractor
        print "word feature extractor: ", data.word_feature_extractor
        print "use crf: ", self.use_crf
        self.gpu = data.HP_gpu
        self.average_batch = data.average_batch_loss
        label_size = {}
        for idtask in range(data.HP_tasks):
            label_size[idtask] = data.label_alphabet_sizes[idtask]
            data.label_alphabet_sizes[idtask] += 2

        self.word_hidden = WordSequence(data)
        if self.use_crf:
            self.crf = {}
            self.crf = {idtask: CRF(label_size[idtask], self.gpu)
                        for idtask in range(data.HP_tasks)}
        self.data = data

        self.tasks_weights = self.data.HP_tasks_weights

    def set_tasks_weights(self, task_weights):
        self.tasks_weights = task_weights

    def neg_log_likelihood_loss(self, word_inputs, feature_inputs, word_seq_lengths,
                                char_inputs, char_seq_lengths, char_seq_recover, batch_label, mask, activated_outputs,
                                inference):
        outs = self.word_hidden(word_inputs, feature_inputs, word_seq_lengths, char_inputs, char_seq_lengths,
                                char_seq_recover, inference)
        batch_size = word_inputs.size(0)
        seq_len = word_inputs.size(1)
        losses = []
        scores = []
        tag_seqs = []

        if self.use_crf:
            for idtask, out in enumerate(outs):
                loss = self.crf[idtask].neg_log_likelihood_loss(out, mask, batch_label[idtask])
                score, tag_seq = self.crf[idtask]._viterbi_decode(out, mask)
                losses.append(self.tasks_weights[idtask] * loss)
                scores.append(score)
                tag_seqs.append(tag_seq)
        else:
            for idtask, out in enumerate(outs):
                loss_function = nn.NLLLoss(ignore_index=0, size_average=False)
                out = out.view(batch_size * seq_len, -1)
                score = F.log_softmax(out, 1)
                aux_loss = loss_function(score, batch_label[idtask].view(batch_size * seq_len))
                if idtask in activated_outputs:
                    losses.append(self.tasks_weights[idtask] * aux_loss)
                    self.word_hidden.hidden2tagList[idtask].weight.requires_grad = True
                    self.word_hidden.hidden2tagList[idtask].bias.requires_grad = True
                else:
                    losses.append(0 * aux_loss)
                    self.word_hidden.hidden2tagList[idtask].weight.requires_grad = False
                    self.word_hidden.hidden2tagList[idtask].bias.requires_grad = False

                _, tag_seq = torch.max(score, 1)
                tag_seq = tag_seq.view(batch_size, seq_len)

                scores.append(score)
                tag_seqs.append(tag_seq)

        total_loss = sum(losses)

        if self.average_batch:
            total_loss = total_loss / batch_size

        return total_loss, losses, tag_seqs

    def forward(self, word_inputs, feature_inputs, word_seq_lengths, char_inputs, char_seq_lengths, char_seq_recover,
                mask, inference):
        outs = self.word_hidden(word_inputs, feature_inputs, word_seq_lengths, char_inputs, char_seq_lengths,
                                char_seq_recover, inference)

        batch_size = word_inputs.size(0)
        seq_len = word_inputs.size(1)
        scores = []
        tag_seqs = []
        if self.use_crf:
            for idtask, out in enumerate(outs):
                score, tag_seq = self.crf[idtask]._viterbi_decode(out, mask)
                scores.append(score)
                tag_seqs.append(tag_seq)
        else:

            for idtask, out in enumerate(outs):
                out = out.view(batch_size * seq_len, -1)
                _, tag_seq = torch.max(out, 1)
                tag_seq = tag_seq.view(batch_size, seq_len)
                tag_seq = mask.long() * tag_seq
                tag_seqs.append(tag_seq)

        return tag_seqs

    def decode_nbest(self, word_inputs, feature_inputs, word_seq_lengths,
                     char_inputs, char_seq_lengths, char_seq_recover, mask,
                     inference, nbest):

        if not self.use_crf:
            print "Nbest output is currently supported only for CRF! Exit..."
            exit(0)

        outs = self.word_hidden(word_inputs, feature_inputs, word_seq_lengths, char_inputs, char_seq_lengths,
                                char_seq_recover, inference)
        batch_size = word_inputs.size(0)
        seq_len = word_inputs.size(1)

        scores, tag_seqs = [], []
        for idtask, out in enumerate(outs):
            score, tag_seq = self.crf[idtask]._viterbi_decode_nbest(out, mask,
                                                                    nbest)  # self.crf[idtask]._viterbi_decode(out,mask)
            scores.append(score)
            tag_seqs.append(tag_seq)
        return scores, tag_seqs
