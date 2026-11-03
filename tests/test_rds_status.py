"""Keep the separate RDS status command on the selected AWS profile."""

from types import SimpleNamespace
from unittest.mock import Mock

from src.cli import rds_manager


def test_status_uses_the_provisioners_selected_profile(monkeypatch, capsys):
    client = Mock()
    client.describe_db_instances.return_value = {
        "DBInstances": [
            {
                "DBInstanceStatus": "available",
                "Endpoint": {"Address": "test.example", "Port": 5432},
                "Engine": "postgres",
                "EngineVersion": "15",
                "DBInstanceClass": "db.test",
                "AllocatedStorage": 500,
                "StorageType": "gp3",
                "MultiAZ": False,
                "PubliclyAccessible": False,
                "BackupRetentionPeriod": 7,
            }
        ]
    }
    provisioner = Mock(return_value=SimpleNamespace(rds_client=client))
    monkeypatch.setattr(rds_manager, "RDSProvisioner", provisioner)
    monkeypatch.setattr("boto3.client", Mock(side_effect=RuntimeError("default profile used")))
    args = SimpleNamespace(region="us-east-1", profile="build-profile", instance_id="test-rds")
    assert rds_manager.cmd_status(args) == 0
    assert "test.example" in capsys.readouterr().out
    provisioner.assert_called_once_with(region="us-east-1", profile_name="build-profile")
    client.describe_db_instances.assert_called_once_with(DBInstanceIdentifier="test-rds")
