# coding=utf-8
# Copyright 2020 The Trax Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Lint as: python3
"""Tests for trax.layers.research.efficient_attention."""

import jax
import numpy as np
from tensorflow import test

from trax import math
from trax import shapes
from trax.layers.research import efficient_attention
from trax.math import numpy as jnp


class EfficientAttentionTest(test.TestCase):

  def test_self_attention(self):
    with math.use_backend('jax'):
      layer = efficient_attention.SelfAttention(
          n_heads=5, d_qk=7, d_v=17, share_qk=False, causal=True,
          chunk_len=8, n_chunks_before=1, n_chunks_after=0,
          use_reference_code=True, attention_dropout=0.0, mode='train')
      x = np.ones((3, 32, 8)).astype(np.float32)
      _, _ = layer.init(shapes.signature(x))
      y = layer(x)
      self.assertEqual(y.shape, x.shape)

  def test_self_attention_tf(self):
    with math.use_backend('tf'):
      layer = efficient_attention.SelfAttention(
          n_heads=5, d_qk=7, d_v=17, share_qk=False, causal=True,
          chunk_len=8, n_chunks_before=1, n_chunks_after=0,
          use_reference_code=True, attention_dropout=0.0, mode='train')
      x = np.ones((3, 32, 8)).astype(np.float32)
      _, _ = layer.init(shapes.signature(x))
      y = layer(x)
      self.assertEqual(y.shape, x.shape)

  def test_lsh_self_attention(self):
    with math.use_backend('jax'):
      layer = efficient_attention.LSHSelfAttention(
          n_heads=5, d_qk=7, d_v=17, causal=True,
          chunk_len=8, n_chunks_before=1, n_chunks_after=0,
          n_hashes=2, n_buckets=4,
          use_reference_code=True, attention_dropout=0.0, mode='train')
      x = np.ones((3, 32, 8)).astype(np.float32)
      _, _ = layer.init(shapes.signature(x))
      y = layer(x)
      self.assertEqual(y.shape, x.shape)

  def _run_forward_and_backward(self, model, inp, weights, state):
    def forward(inp, weights):
      return model.pure_fn(
          inp, weights, state, rng=jax.random.PRNGKey(0))
    out, vjpfun, new_state = jax.vjp(forward, inp, weights, has_aux=True)
    inp_grad, weights_grad = vjpfun(np.ones_like(inp))
    return out, new_state, inp_grad, weights_grad

  def _test_equivalence_to_reference_code(
      self, model_cls, inp, input_signature, common_kwargs, *test_kwargs):
    ref_model = model_cls(use_reference_code=True, **common_kwargs)
    rng = math.random.get_prng(123)
    weights, state = ref_model.init(input_signature, rng)

    ref_all = self._run_forward_and_backward(ref_model, inp, weights, state)
    ref_out, ref_state, ref_inp_grad, ref_weights_grad = ref_all

    for kwargs in test_kwargs:
      test_model = model_cls(**common_kwargs, **kwargs)
      state = test_model.init(input_signature, rng)[1]
      test_all = self._run_forward_and_backward(test_model, inp, weights, state)
      test_out, test_state, test_inp_grad, test_weights_grad = test_all

      self.assertEqual(jax.tree_structure(ref_out),
                       jax.tree_structure(test_out))
      self.assertEqual(jax.tree_structure(ref_state),
                       jax.tree_structure(test_state))
      self.assertEqual(jax.tree_structure(ref_inp_grad),
                       jax.tree_structure(test_inp_grad))
      self.assertEqual(jax.tree_structure(ref_weights_grad),
                       jax.tree_structure(test_weights_grad))

      check_close = lambda x, y: self.assertAllClose(x, y, rtol=1e-3, atol=1e-3)
      jax.tree_multimap(check_close, ref_out, test_out)
      jax.tree_multimap(check_close, ref_state, test_state)
      jax.tree_multimap(check_close, ref_inp_grad, test_inp_grad)
      jax.tree_multimap(check_close, ref_weights_grad, test_weights_grad)

  def test_batching_self_attention(self):
    with math.use_backend('jax'):
      common_kwargs = dict(
          n_heads=6, d_qk=7, d_v=17, share_qk=False, causal=True,
          chunk_len=5, n_chunks_before=1, n_chunks_after=0,
          attention_dropout=0.2, output_dropout=0.1, mode='train',
      )
      test_kwargs = []
      for n_parallel_heads in [1, 3, 6, 12]:
        for use_python_loop in [True, False]:
          test_kwargs.append(dict(n_parallel_heads=n_parallel_heads,
                                  use_python_loop=use_python_loop))

      x = jax.random.uniform(
          jax.random.PRNGKey(0), (2, 10, 13), dtype=jnp.float32)
      input_signature = shapes.signature(x)
      self._test_equivalence_to_reference_code(
          efficient_attention.SelfAttention,
          x, input_signature,
          common_kwargs, *test_kwargs)

  def test_batching_lsh_self_attention(self):
    with math.use_backend('jax'):
      common_kwargs = dict(
          n_heads=6, d_qk=7, d_v=17, causal=True,
          chunk_len=5, n_chunks_before=1, n_chunks_after=0,
          n_hashes=2, n_buckets=4,
          attention_dropout=0.2, output_dropout=0.1, mode='train',
      )
      test_kwargs = []
      for n_parallel_heads in [1, 3, 6, 12]:
        for use_python_loop in [True, False]:
          test_kwargs.append(dict(n_parallel_heads=n_parallel_heads,
                                  use_python_loop=use_python_loop))

      x = jax.random.uniform(
          jax.random.PRNGKey(0), (2, 10, 13), dtype=jnp.float32)
      input_signature = shapes.signature(x)
      self._test_equivalence_to_reference_code(
          efficient_attention.LSHSelfAttention,
          x, input_signature,
          common_kwargs, *test_kwargs)

  def _test_fast_inference(
      self, model_cls, x, input_signature, common_kwargs, *test_kwargs):
    ref_model = model_cls(use_reference_code=True, mode='eval', **common_kwargs)
    weights, state = ref_model.init(input_signature)

    ref_out, _ = ref_model.pure_fn(
        x, weights, state, rng=jax.random.PRNGKey(0))

    def get_slice(pytree, i):
      def get_slice_for_val(x):
        if isinstance(x, shapes.ShapeDtype):
          return shapes.ShapeDtype(shape=x.shape[:1] + (1,) + x.shape[2:],
                                   dtype=x.dtype)
        else:
          return x[:, i:i+1]
      return jax.tree_map(get_slice_for_val, pytree)

    seqlen = x[0].shape[1] if isinstance(x, (tuple, list)) else x.shape[1]

    for kwargs in test_kwargs:
      test_model = model_cls(mode='predict', **common_kwargs, **kwargs)
      cur_state = test_model.init(get_slice(input_signature, 0))[1]
      out = []
      for i in range(seqlen):
        cur_out, cur_state = test_model.pure_fn(
            get_slice(x, i), weights, cur_state, jax.random.PRNGKey(0))
        out.append(cur_out)
      out = jnp.concatenate(out, axis=1)

      self.assertAllClose(out, ref_out, rtol=1e-3, atol=1e-3)

  def test_fast_inference_self_attention(self):
    with math.use_backend('jax'):
      common_kwargs = dict(
          n_heads=6, d_qk=7, d_v=17, share_qk=False, causal=True,
          chunk_len=5, n_chunks_before=1, n_chunks_after=0,
          attention_dropout=0.0, output_dropout=0.0,
      )
      test_kwargs = []
      for n_parallel_heads in [1, 3, 6, 12]:
        for use_python_loop in [True, False]:
          test_kwargs.append(dict(n_parallel_heads=n_parallel_heads,
                                  use_python_loop=use_python_loop))

      x = jax.random.uniform(
          jax.random.PRNGKey(0), (2, 10, 13), dtype=jnp.float32)
      input_signature = shapes.signature(x)
      self._test_fast_inference(
          efficient_attention.SelfAttention,
          x, input_signature,
          common_kwargs, *test_kwargs)


if __name__ == '__main__':
  test.main()
