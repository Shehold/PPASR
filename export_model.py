import argparse
import functools
import os
from datetime import datetime

import paddle
import paddle.distributed as dist
from paddle.static import InputSpec

from data_utils.featurizer.audio_featurizer import AudioFeaturizer
from data_utils.featurizer.text_featurizer import TextFeaturizer
from utils.utils import add_arguments, print_arguments
from model_utils.deepspeech2.model import DeepSpeech2Model

parser = argparse.ArgumentParser(description=__doc__)
add_arg = functools.partial(add_arguments, argparser=parser)
add_arg('use_model',        str,   'deepspeech2',              '所使用的模型')
add_arg('dataset_vocab',    str,   'dataset/vocabulary.txt',   '数据字典的路径')
add_arg('save_model',       str,   'models/deepspeech2/',          '模型保存的路径')
add_arg('resume_model',     str,   'models/deepspeech2/epoch_50',  '恢复训练，当为None则不使用预训练模型')
args = parser.parse_args()


def export(args):
    # 获取训练数据
    audio_featurizer = AudioFeaturizer()
    text_featurizer = TextFeaturizer(args.dataset_vocab)

    # 获取模型
    if args.use_model == 'deepspeech2':
        base_model = DeepSpeech2Model(feat_size=audio_featurizer.feature_dim, vocab_size=text_featurizer.vocab_size)
    else:
        raise Exception('没有该模型：%s' % args.use_model)

    if dist.get_rank() == 0:
        print('[{}] input_size的第三个参数是变长的，这里为了能查看输出的大小变化，指定了一个值！'.format(datetime.now()))
        paddle.summary(base_model, input_size=[(None, audio_featurizer.feature_dim, 970), (None,)],
                       dtypes=[paddle.float32, paddle.int64])

    # 加载预训练模型
    resume_model_path = os.path.join(args.resume_model, 'model.pdparams')
    assert os.path.exists(resume_model_path), "恢复模型不存在！"
    base_model.set_state_dict(paddle.load(resume_model_path))
    print('[{}] 成功恢复模型参数和优化方法参数'.format(datetime.now()))

    # 在输出层加上Softmax
    class Model(paddle.nn.Layer):
        def __init__(self, model):
            super(Model, self).__init__()
            self.model = model
            self.softmax = paddle.nn.Softmax()

        def forward(self, audio, audio_len):
            logits, x_lensx = self.model(audio, audio_len)
            output = self.softmax(logits)
            return output

    model = Model(base_model)
    infer_model_path = os.path.join(args.save_model, 'infer')
    if not os.path.exists(infer_model_path):
        os.makedirs(infer_model_path)
    paddle.jit.save(layer=model,
                    path=os.path.join(infer_model_path, 'model'),
                    input_spec=[InputSpec(shape=(-1, audio_featurizer.feature_dim, -1), dtype=paddle.float32),
                                InputSpec(shape=(-1,), dtype=paddle.int64)])
    print("预测模型已保存：%s" % infer_model_path)


if __name__ == '__main__':
    print_arguments(args)
    export(args)
