#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
import tempfile

import boto3
import mock
import pytest
from botocore.exceptions import NoCredentialsError

from airflow.exceptions import AirflowException
from airflow.models import Connection
from airflow.providers.amazon.aws.hooks.s3 import S3Hook, provide_bucket_name

try:
    from moto import mock_s3
except ImportError:
    mock_s3 = None


@pytest.mark.skipif(mock_s3 is None, reason='moto package not present')
class TestAwsS3Hook:

    @mock_s3
    def test_get_conn(self):
        hook = S3Hook()
        assert hook.get_conn() is not None

    def test_parse_s3_url(self):
        parsed = S3Hook.parse_s3_url("s3://test/this/is/not/a-real-key.txt")
        assert parsed == ("test", "this/is/not/a-real-key.txt"), "Incorrect parsing of the s3 url"

    def test_check_for_bucket(self, s3_bucket):
        hook = S3Hook()
        assert hook.check_for_bucket(s3_bucket) is True
        assert hook.check_for_bucket('not-a-bucket') is False

    def test_check_for_bucket_raises_error_with_invalid_conn_id(self, s3_bucket, monkeypatch):
        monkeypatch.delenv('AWS_PROFILE', raising=False)
        monkeypatch.delenv('AWS_ACCESS_KEY_ID', raising=False)
        monkeypatch.delenv('AWS_SECRET_ACCESS_KEY', raising=False)
        hook = S3Hook(aws_conn_id="does_not_exist")
        with pytest.raises(NoCredentialsError):
            hook.check_for_bucket(s3_bucket)

    @mock_s3
    def test_get_bucket(self):
        hook = S3Hook()
        assert hook.get_bucket('bucket') is not None

    @mock_s3
    def test_create_bucket_default_region(self):
        hook = S3Hook()
        hook.create_bucket(bucket_name='new_bucket')
        assert hook.get_bucket('new_bucket') is not None

    @mock_s3
    def test_create_bucket_us_standard_region(self, monkeypatch):
        monkeypatch.delenv('AWS_DEFAULT_REGION', raising=False)

        hook = S3Hook()
        hook.create_bucket(bucket_name='new_bucket', region_name='us-east-1')
        bucket = hook.get_bucket('new_bucket')
        assert bucket is not None
        region = bucket.meta.client.get_bucket_location(Bucket=bucket.name).get('LocationConstraint', None)
        # https://github.com/spulec/moto/pull/1961
        # If location is "us-east-1", LocationConstraint should be None
        assert region is None

    @mock_s3
    def test_create_bucket_other_region(self):
        hook = S3Hook()
        hook.create_bucket(bucket_name='new_bucket', region_name='us-east-2')
        bucket = hook.get_bucket('new_bucket')
        assert bucket is not None
        region = bucket.meta.client.get_bucket_location(Bucket=bucket.name).get('LocationConstraint', None)
        assert region == 'us-east-2'

    def test_check_for_prefix(self, s3_bucket):
        hook = S3Hook()
        bucket = hook.get_bucket(s3_bucket)
        bucket.put_object(Key='a', Body=b'a')
        bucket.put_object(Key='dir/b', Body=b'b')

        assert hook.check_for_prefix(bucket_name=s3_bucket, prefix='dir/', delimiter='/') is True
        assert hook.check_for_prefix(bucket_name=s3_bucket, prefix='a', delimiter='/') is False

    def test_list_prefixes(self, s3_bucket):
        hook = S3Hook()
        bucket = hook.get_bucket(s3_bucket)
        bucket.put_object(Key='a', Body=b'a')
        bucket.put_object(Key='dir/b', Body=b'b')

        assert hook.list_prefixes(s3_bucket, prefix='non-existent/') is None
        assert ['dir/'] == hook.list_prefixes(s3_bucket, delimiter='/')
        assert ['a'] == hook.list_keys(s3_bucket, delimiter='/')
        assert ['dir/b'] == hook.list_keys(s3_bucket, prefix='dir/')

    def test_list_prefixes_paged(self, s3_bucket):
        hook = S3Hook()
        bucket = hook.get_bucket(s3_bucket)

        # we dont need to test the paginator that's covered by boto tests
        keys = ["%s/b" % i for i in range(2)]
        dirs = ["%s/" % i for i in range(2)]
        for key in keys:
            bucket.put_object(Key=key, Body=b'a')

        assert sorted(dirs) == sorted(hook.list_prefixes(s3_bucket, delimiter='/', page_size=1))

    def test_list_keys(self, s3_bucket):
        hook = S3Hook()
        bucket = hook.get_bucket(s3_bucket)
        bucket.put_object(Key='a', Body=b'a')
        bucket.put_object(Key='dir/b', Body=b'b')

        assert hook.list_keys(s3_bucket, prefix='non-existent/') is None
        assert ['a', 'dir/b'] == hook.list_keys(s3_bucket)
        assert ['a'] == hook.list_keys(s3_bucket, delimiter='/')
        assert ['dir/b'] == hook.list_keys(s3_bucket, prefix='dir/')

    def test_list_keys_paged(self, s3_bucket):
        hook = S3Hook()
        bucket = hook.get_bucket(s3_bucket)

        keys = [str(i) for i in range(2)]
        for key in keys:
            bucket.put_object(Key=key, Body=b'a')

        assert sorted(keys) == sorted(hook.list_keys(s3_bucket, delimiter='/', page_size=1))

    def test_check_for_key(self, s3_bucket):
        hook = S3Hook()
        bucket = hook.get_bucket(s3_bucket)
        bucket.put_object(Key='a', Body=b'a')

        assert hook.check_for_key('a', s3_bucket) is True
        assert hook.check_for_key('s3://{}//a'.format(s3_bucket)) is True
        assert hook.check_for_key('b', s3_bucket) is False
        assert hook.check_for_key('s3://{}//b'.format(s3_bucket)) is False

    def test_check_for_key_raises_error_with_invalid_conn_id(self, monkeypatch, s3_bucket):
        monkeypatch.delenv('AWS_PROFILE', raising=False)
        monkeypatch.delenv('AWS_ACCESS_KEY_ID', raising=False)
        monkeypatch.delenv('AWS_SECRET_ACCESS_KEY', raising=False)
        hook = S3Hook(aws_conn_id="does_not_exist")
        with pytest.raises(NoCredentialsError):
            hook.check_for_key('a', s3_bucket)

    def test_get_key(self, s3_bucket):
        hook = S3Hook()
        bucket = hook.get_bucket(s3_bucket)
        bucket.put_object(Key='a', Body=b'a')

        assert hook.get_key('a', s3_bucket).key == 'a'
        assert hook.get_key('s3://{}/a'.format(s3_bucket)).key == 'a'

    def test_read_key(self, s3_bucket):
        hook = S3Hook()
        bucket = hook.get_bucket(s3_bucket)
        bucket.put_object(Key='my_key', Body=b'Cont\xC3\xA9nt')

        assert hook.read_key('my_key', s3_bucket) == 'Contént'

    # As of 1.3.2, Moto doesn't support select_object_content yet.
    @mock.patch('airflow.providers.amazon.aws.hooks.base_aws.AwsBaseHook.get_client_type')
    def test_select_key(self, mock_get_client_type, s3_bucket):
        mock_get_client_type.return_value.select_object_content.return_value = \
            {'Payload': [{'Records': {'Payload': b'Cont\xC3\xA9nt'}}]}
        hook = S3Hook()
        assert hook.select_key('my_key', s3_bucket) == 'Contént'

    def test_check_for_wildcard_key(self, s3_bucket):
        hook = S3Hook()
        bucket = hook.get_bucket(s3_bucket)
        bucket.put_object(Key='abc', Body=b'a')
        bucket.put_object(Key='a/b', Body=b'a')

        assert hook.check_for_wildcard_key('a*', s3_bucket) is True
        assert hook.check_for_wildcard_key('abc', s3_bucket) is True
        assert hook.check_for_wildcard_key('s3://{}//a*'.format(s3_bucket)) is True
        assert hook.check_for_wildcard_key('s3://{}//abc'.format(s3_bucket)) is True

        assert hook.check_for_wildcard_key('a', s3_bucket) is False
        assert hook.check_for_wildcard_key('b', s3_bucket) is False
        assert hook.check_for_wildcard_key('s3://{}//a'.format(s3_bucket)) is False
        assert hook.check_for_wildcard_key('s3://{}//b'.format(s3_bucket)) is False

    def test_get_wildcard_key(self, s3_bucket):
        hook = S3Hook()
        bucket = hook.get_bucket(s3_bucket)
        bucket.put_object(Key='abc', Body=b'a')
        bucket.put_object(Key='a/b', Body=b'a')

        # The boto3 Class API is _odd_, and we can't do an isinstance check as
        # each instance is a different class, so lets just check one property
        # on S3.Object. Not great but...
        assert hook.get_wildcard_key('a*', s3_bucket).key == 'a/b'
        assert hook.get_wildcard_key('a*', s3_bucket, delimiter='/').key == 'abc'
        assert hook.get_wildcard_key('abc', s3_bucket, delimiter='/').key == 'abc'
        assert hook.get_wildcard_key('s3://{}/a*'.format(s3_bucket)).key == 'a/b'
        assert hook.get_wildcard_key('s3://{}/a*'.format(s3_bucket), delimiter='/').key == 'abc'
        assert hook.get_wildcard_key('s3://{}/abc'.format(s3_bucket), delimiter='/').key == 'abc'

        assert hook.get_wildcard_key('a', s3_bucket) is None
        assert hook.get_wildcard_key('b', s3_bucket) is None
        assert hook.get_wildcard_key('s3://{}/a'.format(s3_bucket)) is None
        assert hook.get_wildcard_key('s3://{}/b'.format(s3_bucket)) is None

    def test_load_string(self, s3_bucket):
        hook = S3Hook()
        hook.load_string("Contént", "my_key", s3_bucket)
        resource = boto3.resource('s3').Object(s3_bucket, 'my_key')  # pylint: disable=no-member
        assert resource.get()['Body'].read() == b'Cont\xC3\xA9nt'

    def test_load_bytes(self, s3_bucket):
        hook = S3Hook()
        hook.load_bytes(b"Content", "my_key", s3_bucket)
        resource = boto3.resource('s3').Object(s3_bucket, 'my_key')  # pylint: disable=no-member
        assert resource.get()['Body'].read() == b'Content'

    def test_load_fileobj(self, s3_bucket):
        hook = S3Hook()
        with tempfile.TemporaryFile() as temp_file:
            temp_file.write(b"Content")
            temp_file.seek(0)
            hook.load_file_obj(temp_file, "my_key", s3_bucket)
            resource = boto3.resource('s3').Object(s3_bucket, 'my_key')  # pylint: disable=no-member
            assert resource.get()['Body'].read() == b'Content'

    @mock.patch.object(S3Hook, 'get_connection', return_value=Connection(schema='test_bucket'))
    def test_provide_bucket_name(self, mock_get_connection):

        class FakeS3Hook(S3Hook):

            @provide_bucket_name
            def test_function(self, bucket_name=None):
                return bucket_name

            # pylint: disable=unused-argument
            @provide_bucket_name
            def test_function_with_key(self, key, bucket_name=None):
                return bucket_name

            # pylint: disable=unused-argument
            @provide_bucket_name
            def test_function_with_wildcard_key(self, wildcard_key, bucket_name=None):
                return bucket_name

        fake_s3_hook = FakeS3Hook()
        test_bucket_name = fake_s3_hook.test_function()
        test_bucket_name_with_key = fake_s3_hook.test_function_with_key('test_key')
        test_bucket_name_with_wildcard_key = fake_s3_hook.test_function_with_wildcard_key('test_*_key')

        assert test_bucket_name == mock_get_connection.return_value.schema
        assert test_bucket_name_with_key is None
        assert test_bucket_name_with_wildcard_key is None

    def test_delete_objects_key_does_not_exist(self, s3_bucket):
        hook = S3Hook()
        with pytest.raises(AirflowException) as err:
            hook.delete_objects(bucket=s3_bucket, keys=['key-1'])

        assert isinstance(err.value, AirflowException)
        assert str(err.value) == "Errors when deleting: ['key-1']"

    def test_delete_objects_one_key(self, mocked_s3_res, s3_bucket):
        key = 'key-1'
        mocked_s3_res.Object(s3_bucket, key).put(Body=b'Data')
        hook = S3Hook()
        hook.delete_objects(bucket=s3_bucket, keys=[key])
        assert [o.key for o in mocked_s3_res.Bucket(s3_bucket).objects.all()] == []

    def test_delete_objects_many_keys(self, mocked_s3_res, s3_bucket):
        num_keys_to_remove = 1001
        keys = []
        for index in range(num_keys_to_remove):
            key = 'key-{}'.format(index)
            mocked_s3_res.Object(s3_bucket, key).put(Body=b'Data')
            keys.append(key)

        assert sum(1 for _ in mocked_s3_res.Bucket(s3_bucket).objects.all()) == num_keys_to_remove
        hook = S3Hook()
        hook.delete_objects(bucket=s3_bucket, keys=keys)
        assert [o.key for o in mocked_s3_res.Bucket(s3_bucket).objects.all()] == []
